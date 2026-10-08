import json
import os
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
from odoo.addons.omni_telegram.tools.operations_status import collect


@tagged("post_install", "-at_install")
class TestTelegramSandbox(TestOmniCommands):
    def test_create_fills_identity_without_activating_anything(self):
        config = self.account._telegram_config()
        provisioned = environment(config)
        bundle = json.loads(provisioned[REFERENCE])
        bot = '987654322'
        bundle['bot_id'] = bot
        bundle['token'] = bot + ':' + bundle['token'].split(':', 1)[1]
        provisioned[REFERENCE] = json.dumps(bundle)
        with patch.dict(os.environ, provisioned):
            account = self.env['omni.account'].with_user(self.manager).create({
                'name': 'Auto-discovered bot',
                'purpose_id': self.purpose.id,
                'channel_type_id': self.type.id,
                'company_id': self.company.id,
                'credential_reference': REFERENCE,
            })
        self.assertEqual(account.external_account_key, bot)
        self.assertEqual(account.namespace, bot)
        self.assertFalse(account.telegram_sandbox_authorized)
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            binding = self.env[model].with_user(self.manager).create({
                'name': 'Automatically filled identity',
                'channel_id': self.channel.id, 'account_id': account.id,
            })
            self.assertEqual(binding.external_key, bot)
        self.assertFalse(self.channel.selected_sender_id)
        self.assertFalse(self.channel.dispatch_enabled)

    def test_setup_derives_bot_identity_and_bindings(self):
        config = self.account._telegram_config()
        with patch.dict(os.environ, environment(config)):
            account = self.env['omni.account'].with_user(self.manager).new({
                'channel_type_id': self.type.id,
                'company_id': self.company.id,
                'purpose_id': self.purpose.id,
                'credential_reference': REFERENCE,
            })
            account._onchange_telegram_identity()
            self.assertEqual(account.external_account_key, BOT)
            self.assertEqual(account.namespace, BOT)
            self.assertNotIn(':', account.external_account_key)
            with self.assertRaises(AccessError):
                self.account.with_user(self.operator)._discover_bot_identity(REFERENCE, self.company.id)
            with self.assertRaises(AccessError):
                self.account.with_user(self.manager)._discover_bot_identity(
                    REFERENCE, self.other_company.id,
                )
            # Wrong database binding fails without echoing bundle contents.
            bad = environment(config)
            bundle = json.loads(bad[REFERENCE])
            bundle['database'] = 'another-database'
            bad[REFERENCE] = json.dumps(bundle)
            with patch.dict(os.environ, bad), self.assertRaises(UserError) as error:
                self.account.with_user(self.manager)._discover_bot_identity(REFERENCE, self.company.id)
            self.assertNotIn(SECRET, str(error.exception))
        # Defaults on an unsaved sender/endpoint need no secret access.
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            binding = self.env[model].with_user(self.manager).new({
                'channel_id': self.channel.id, 'account_id': self.account.id,
            })
            binding._onchange_telegram_binding_identity()
            self.assertEqual(binding.external_key, BOT)

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

    def test_operations_snapshot_is_restricted_and_content_free(self):
        command = self._reply()
        with self.assertRaises(AccessError):
            collect(self.env(user=self.operator))
        before = len(self.http.calls)
        result = collect(self.env)
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['counts']['unknown_outcomes'], 0)
        self.assertNotIn(command.body, json.dumps(result))
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(len(self.http.calls), before)
        claim = self.env['omni.command']._claim_next()
        self.http.send_result = TimeoutError('synthetic timeout')
        command._finish_attempt(claim, dispatch_claim(claim))
        result = collect(self.env)
        self.assertEqual(result['severity'], 'critical')
        self.assertEqual(result['counts']['unknown_outcomes'], 1)
