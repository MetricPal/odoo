import json
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests import tagged

from .test_provider import BOT, REFERENCE, SECRET, FakeHTTP, environment, fixture
from odoo.addons.omni_channel.providers.dispatch import dispatch_claim
from odoo.addons.omni_channel.providers.inbound import IngressRejected
from odoo.addons.omni_channel.tests.test_commands import TestOmniCommands
from odoo.addons.omni_telegram.providers.secrets import resolve
from odoo.addons.omni_telegram.providers.telegram import TelegramAdapter


@tagged("post_install", "-at_install")
class TestTelegramSandbox(TestOmniCommands):
    def setUp(self):
        super().setUp()
        self.type = self.env.ref("omni_channel.channel_type_telegram")
        self.channel = self.env["omni.channel"].create(
            {
                "name": "Telegram sandbox",
                "purpose_id": self.purpose.id,
                "channel_type_id": self.type.id,
                "approval_type_id": self.policy.id,
            },
        )
        self.account = self.env["omni.account"].create(
            {
                "name": "Synthetic bot",
                "purpose_id": self.purpose.id,
                "channel_type_id": self.type.id,
                "external_account_key": BOT,
                "namespace": BOT,
                "credential_reference": REFERENCE,
                "telegram_sandbox_recipients": "12345",
                "telegram_sandbox_evidence": "Synthetic test authorization; no real provider access.",
            },
        )
        self.sender = self.env["omni.outbound.sender"].create(
            {
                "name": "Synthetic sender",
                "channel_id": self.channel.id,
                "account_id": self.account.id,
                "external_key": BOT,
            },
        )
        self.endpoint = self.env["omni.inbound.endpoint"].create(
            {
                "name": "Synthetic endpoint",
                "channel_id": self.channel.id,
                "account_id": self.account.id,
                "external_key": BOT,
            },
        )
        self.intake = self.env["omni.inbound.policy"].create(
            {"name": "Private text sandbox", "channel_id": self.channel.id},
        )
        self.http = FakeHTTP()
        config = self.account._telegram_config()
        self.adapter = TelegramAdapter(
            self.http, lambda ref, binding: resolve(ref, binding, environment(config)),
        )
        patcher = patch.dict(
            "odoo.addons.omni_channel.providers.base._ADAPTERS",
            {"telegram": lambda: self.adapter},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _activate(self):
        self.account.with_user(self.manager).action_authorize_telegram_sandbox()
        self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.intake.with_user(self.manager).action_activate()
        self.endpoint.with_user(self.manager).action_enable()

    def _conversation(self):
        self.endpoint._receive(
            json.dumps(fixture()).encode(), {"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        self.env["omni.webhook.event"]._process_batch()
        return (
            self.env["omni.conversation"]
            .search([("endpoint_id", "=", self.endpoint.id)])
            .with_user(self.operator)
        )

    def _reply(self):
        self._activate()
        conversation = self._conversation()
        action = conversation.action_prepare_reply()
        command = (
            self.env["omni.command"].browse(action["res_id"]).with_user(self.operator)
        )
        command.body = "We can help."
        command.action_submit()
        command.approval_request_id.with_user(self.approver).action_approve()
        command.action_enqueue_approved()
        grant = self.env["omni.consent"].create(
            {
                "channel_id": self.channel.id,
                "namespace": BOT,
                "recipient": "12345",
                "evidence": "Explicit synthetic recipient consent.",
            },
        )
        grant.with_user(self.manager).action_confirm()
        self.channel.with_user(self.manager).action_enable_telegram_dispatch()
        return command.sudo()

    def test_verified_intake_and_separately_approved_reply(self):
        command = self._reply()
        self.assertFalse(any(method == "sendMessage" for method, _ in self.http.calls))
        claim = self.env["omni.command"]._claim_next()
        self.assertTrue(claim)
        self.assertEqual(
            json.loads(claim.adapter_config_json)["database"], self.env.cr.dbname,
        )
        result = dispatch_claim(claim)
        self.assertTrue(command._finish_attempt(claim, result))
        self.assertEqual(command.state, "accepted")
        self.assertEqual(command.provider_message_key, BOT + ":12345:43")
        self.assertEqual(
            sum(method == "sendMessage" for method, _ in self.http.calls), 1,
        )
        self.assertFalse(self.env["omni.command"]._claim_next())

    def test_revoke_holds_queued_work_and_stops_intake(self):
        command = self._reply()
        self.account.with_user(self.manager).action_revoke_telegram_sandbox()
        self.assertFalse(self.channel.dispatch_enabled)
        self.assertEqual(command.state, "held")
        self.assertFalse(self.env["omni.command"]._claim_next())
        self.assertFalse(self.endpoint._allowed())
        with self.assertRaises(IngressRejected):
            self._conversation()
        self.assertFalse(any(method == "sendMessage" for method, _ in self.http.calls))

    def test_roles_direct_writes_and_authorized_configuration_are_guarded(self):
        for user in [self.operator, self.outsider, self.portal]:
            with self.assertRaises(AccessError):
                self.account.with_user(user).action_authorize_telegram_sandbox()
        with self.assertRaises(AccessError):
            self.account.write({"telegram_sandbox_authorized": True})
        with self.assertRaises(AccessError):
            self.account.with_context(default_telegram_sandbox_authorized=True).copy()
        self._activate()
        with self.assertRaises(UserError):
            self.account.with_user(self.manager).write(
                {"telegram_sandbox_recipients": "999"},
            )
        with self.assertRaises(AccessError):
            self.channel.with_user(self.operator).action_enable_telegram_dispatch()

    def test_direct_send_without_verified_conversation_is_refused(self):
        self._activate()
        command = (
            self.env["omni.command"]
            .with_user(self.operator)
            .create(
                {
                    "name": "No conversation",
                    "channel_id": self.channel.id,
                    "recipient": "12345",
                    "body": "Hello",
                    "reason": "Test",
                },
            )
        )
        with self.assertRaises(UserError):
            command.action_submit()
        self.assertFalse(command.approval_request_id)

    def test_failed_identity_verification_cannot_authorize(self):
        self.adapter.check_sender_health = lambda config: type(
            "Health", (), {"healthy": False},
        )()
        with self.assertRaises(UserError):
            self.account.with_user(self.manager).action_authorize_telegram_sandbox()
        self.assertFalse(self.account.telegram_sandbox_authorized)
        self.assertFalse(self.channel.dispatch_enabled)

    def test_operator_can_submit_with_uncached_private_policy(self):
        self._activate()
        conversation = self._conversation()
        action = conversation.action_prepare_reply()
        command = self.env['omni.command'].browse(action['res_id']).with_user(self.operator)
        command.body = 'One reviewed private reply.'
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.intake.with_user(self.operator).read(['state'])
        command.action_submit()
        self.assertEqual(command.state, 'pending')
        with self.assertRaises(AccessError):
            self.intake.with_user(self.operator).read(['state'])

    def test_uncached_paused_policy_still_blocks_operator_submission(self):
        self._activate()
        conversation = self._conversation()
        action = conversation.action_prepare_reply()
        command = self.env['omni.command'].browse(action['res_id']).with_user(self.operator)
        command.body = 'This must not be submitted after policy pause.'
        self.intake.with_user(self.manager).action_pause()
        self.env.invalidate_all()
        with self.assertRaises(UserError):
            command.action_submit()
        self.assertEqual(command.state, 'draft')
        self.assertFalse(command.approval_request_id)

    def test_neutralized_copy_stops_intake_and_dispatch_preserving_history(self):
        command = self._reply()
        original = (command.state, command.body, command.approval_request_id.id)
        crons = self.env['ir.cron'].browse([
            self.env.ref('omni_channel.' + name).id
            for name in ['cron_dispatch', 'cron_inbox', 'cron_inbox_retention']
        ])
        crons.active = True
        self.env.flush_all()
        queries = list(get_neutralization_queries(['omni_channel', 'omni_telegram']))
        self.assertEqual(len(queries), 2)
        for _ in range(2):  # Repeated neutralization remains safe.
            for query in queries:
                self.env.cr.execute(query)
        self.env.invalidate_all()
        self.assertFalse(self.channel.dispatch_enabled)
        self.assertFalse(self.account.telegram_sandbox_authorized)
        self.assertEqual(self.endpoint.state, 'disabled')
        self.assertEqual(self.intake.state, 'paused')
        self.assertFalse(any(crons.mapped('active')))
        self.assertEqual((command.state, command.body, command.approval_request_id.id), original)
        self.assertFalse(self.endpoint._allowed())
        with self.assertRaises(IngressRejected):
            self._conversation()
        self.assertFalse(self.env['omni.command']._claim_next())
        self.assertFalse(any(method == 'sendMessage' for method, _ in self.http.calls))
