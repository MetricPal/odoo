import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_commands import TestOmniCommands
from .test_foundation import HealthyAdapter
from odoo.addons.omni_channel.models.command import internal
from odoo.addons.omni_channel.providers.inbound import InboundEvent, IngressRejected


class MockInboundAdapter(HealthyAdapter):
    inbound_release_ready = True

    def verify_request(self, raw, headers, config):
        return headers.get("X-Test-Signature") == "verified"

    def normalize(self, value, config):
        return tuple(InboundEvent(**row) for row in value["events"])

    def check_endpoint(self, config):
        return True


@tagged("post_install", "-at_install")
class TestOmniInbox(TestOmniCommands):
    def setUp(self):
        super().setUp()
        self.endpoint = self.env["omni.inbound.endpoint"].create(
            {
                "name": "Sandbox inbox",
                "channel_id": self.channel.id,
                "account_id": self.account.id,
                "external_key": "bot-1",
            },
        )
        self.intake_policy = self.env["omni.inbound.policy"].create(
            {"name": "Text intake", "channel_id": self.channel.id},
        )
        self.adapter = MockInboundAdapter()
        for target in (
            "odoo.addons.omni_channel.models.inbox.get_adapter",
            "odoo.addons.omni_channel.providers.inbound.get_adapter",
        ):
            patcher = patch(target, return_value=self.adapter)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.intake_policy.with_user(self.manager).action_activate()
        self.endpoint.with_user(self.manager).action_enable()

    def test_recipient_permission_carries_identity_without_granting_consent(self):
        self._receive()
        self._process()
        conversation = self.env['omni.conversation'].search([
            ('endpoint_id', '=', self.endpoint.id),
        ], limit=1)
        action = conversation.with_user(self.manager).action_recipient_permission()
        self.assertEqual(action['context']['default_recipient'], '12345')
        self.assertEqual(action['context']['default_namespace'], self.account.namespace)
        self.assertEqual(action['context']['default_channel_id'], self.channel.id)
        self.assertFalse(self.env['omni.consent'].search_count([
            ('channel_id', '=', self.channel.id),
        ]))
        with self.assertRaises(AccessError):
            conversation.with_user(self.operator).action_recipient_permission()
        with self.assertRaises(AccessError):
            conversation.with_user(self.outsider).action_recipient_permission()

    def _data(self, **changes):
        data = {
            "event_key": "evt-1",
            "endpoint_key": "bot-1",
            "namespace": "bot-1",
            "kind": "message",
            "sender_key": "12345",
            "thread_key": "12345",
            "message_key": "m-1",
            "body": "Please help with my order.",
            "occurred_at": "2026-10-06 10:00:00",
            "revision": 0,
            "private": True,
        }
        data.update(changes)
        return data

    def _receive(self, **changes):
        self.endpoint._receive(
            json.dumps({"events": [self._data(**changes)]}).encode(),
            {"X-Test-Signature": "verified"},
        )
        return self.env["omni.webhook.event"].search(
            [("endpoint_id", "=", self.endpoint.id)], order="id desc", limit=1,
        )

    def _process(self):
        self.env["omni.webhook.event"]._process_batch()
        return self.env["omni.conversation"].search(
            [("endpoint_id", "=", self.endpoint.id)], limit=1,
        )

    def _block(self, company_wide=False, **changes):
        vals = {
            "company_id": self.company.id,
            "purpose_id": False if company_wide else self.purpose.id,
            "channel_type_id": self.type.id,
            "namespace": "bot-1",
            "external_key": "12345",
            "reason": "Explicit request to stop contact.",
        }
        vals.update(changes)
        return self.env["omni.blocked.identity"].create(vals)

    def test_verified_intake_is_durable_then_normalizes_once_without_contacts(self):
        partners = self.env["res.partner"].search_count([])
        event = self._receive()
        self.assertEqual(event.state, "received")
        self.assertFalse(
            self.env["omni.conversation"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )
        conversation = self._process()
        self.assertEqual(event.state, "processed")
        self.assertFalse(event.payload)
        self.assertEqual(len(conversation.message_ids), 1)
        self._receive()
        self._process()
        self.assertEqual(len(conversation.message_ids), 1)
        self.assertEqual(self.env["res.partner"].search_count([]), partners)
        self.assertFalse(conversation.command_ids)

    def test_invalid_auth_body_and_size_never_persist(self):
        for raw, headers in [
            (b"{}", {}),
            (b"{", {"X-Test-Signature": "verified"}),
            (b"x" * (1024 * 1024 + 1), {"X-Test-Signature": "verified"}),
            (
                json.dumps({"deep": [[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]}).encode(),
                {"X-Test-Signature": "verified"},
            ),
        ]:
            with self.assertRaises(IngressRejected):
                self.endpoint._receive(raw, headers)
        self.assertFalse(
            self.env["omni.webhook.event"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )

    def test_changed_event_key_is_quarantined_without_rewriting_history(self):
        event = self._receive()
        conversation = self._process()
        self._receive(body="Replacement content")
        self.assertTrue(event.collision)
        self.assertEqual(event.state, "unresolved")
        self.assertFalse(event.payload)
        self.assertEqual(conversation.message_ids.body, "Please help with my order.")
        with self.assertRaises(UserError):
            event.with_user(self.manager).action_replay()

    def test_block_precedes_identity_creation_and_unblock_does_not_replay(self):
        block = self._block().with_user(self.operator)
        block.action_block()
        event = self._receive()
        self.assertEqual(event.state, "blocked")
        self.assertFalse(event.payload)
        self.assertTrue(event.identity_hash)
        self.assertNotIn("12345", event.identity_hash)
        self.assertFalse(self._process())
        self.assertFalse(
            self.env["omni.identity"].search_count(
                [("channel_id", "=", self.channel.id)],
            ),
        )
        block.action_unblock()
        self._receive()
        self.assertEqual(event.state, "blocked")
        with self.assertRaises(UserError):
            event.with_user(self.manager).action_replay()

    def test_block_after_intake_purges_pending_body(self):
        event = self._receive()
        block = self._block()
        block.with_user(self.operator).action_block()
        self.assertFalse(event.payload)
        self.assertEqual(event.state, "blocked")
        self.assertFalse(self._process())

    def test_company_block_requires_system_role_and_scope_isolated(self):
        block = self._block(company_wide=True)
        with self.assertRaises(AccessError):
            block.with_user(self.manager).action_block()
        block.action_block()
        self.assertEqual(self._receive().state, "blocked")
        self.assertFalse(
            self.env["omni.blocked.identity"]._matches(
                self.channel, "other-namespace", "12345",
            ),
        )

    def test_expired_block_does_not_suppress(self):
        block = self._block(expires_at=fields.Datetime.now() + timedelta(minutes=1))
        block.action_block()
        with patch(
            "odoo.fields.Datetime.now",
            return_value=fields.Datetime.now() + timedelta(minutes=2),
        ):
            self.assertEqual(self._receive().state, "received")

    def test_policy_pause_and_ownership_change_hold_queued_intake(self):
        event = self._receive()
        self.intake_policy.with_user(self.manager).action_pause()
        self.assertFalse(self._process())
        self.assertEqual(event.state, "unresolved")
        with self.assertRaises(IngressRejected):
            self._receive(event_key="next")
        self.intake_policy.with_user(self.manager).action_activate()
        internal(self.endpoint).write({"ownership_version": 2})
        with self.assertRaises(UserError):
            event.with_user(self.manager).action_replay()

    def test_wrong_endpoint_and_unsupported_types_never_make_conversations(self):
        event = self._receive(endpoint_key="other")
        self.assertEqual(event.state, "unresolved")
        self.assertFalse(event.payload)
        event = self._receive(event_key="group", private=False)
        self.assertEqual(event.state, "ignored")
        self.assertFalse(event.payload)
        self.assertFalse(self._process())

    def test_edits_out_of_order_preserve_revisions_without_regression(self):
        self._receive(event_key="edit-2", kind="edit", revision=2, body="Newest edit")
        conversation = self._process()
        self._receive()
        self._process()
        self.assertEqual(len(conversation.message_ids), 1)
        self.assertEqual(conversation.message_ids.body, "Newest edit")
        self.assertEqual(len(conversation.message_ids.revision_ids), 2)
        event = self._receive(
            event_key="conflicting-revision", revision=2, body="Wrong replacement",
        )
        self._process()
        self.assertEqual(event.state, "unresolved")
        self.assertEqual(conversation.message_ids.body, "Newest edit")

    def test_failure_rolls_back_normalization_and_dead_letter_replays_once(self):
        event = self._receive()
        model = type(self.env["omni.message"])
        with patch.object(
            model, "create", side_effect=UserError("SECRET_PROVIDER_DETAILS"),
        ):
            for _index in range(5):
                internal(event).write({"next_attempt_at": False})
                self._process()
        self.assertEqual(event.state, "dead")
        self.assertEqual(event.attempts, 5)
        self.assertFalse(
            self.env["omni.conversation"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )
        self.assertNotIn("SECRET", event.reason_code)
        event.with_user(self.manager).action_replay()
        self.assertEqual(len(self._process().message_ids), 1)

    def test_retention_purges_bodies_and_revisions_with_legal_hold(self):
        event = self._receive()
        conversation = self._process()
        message = conversation.message_ids
        internal(message).write(
            {"expires_at": fields.Datetime.now() - timedelta(seconds=1)},
        )
        internal(event).write(
            {"expires_at": fields.Datetime.now() - timedelta(seconds=1)},
        )
        self.intake_policy.with_user(self.manager).action_toggle_legal_hold()
        self.env["omni.webhook.event"]._cron_retention()
        self.assertTrue(message.body)
        self.intake_policy.with_user(self.manager).action_toggle_legal_hold()
        self.env["omni.webhook.event"]._cron_retention()
        self.assertFalse(message.body)
        self.assertTrue(message.redacted)
        self.assertFalse(message.revision_ids.body)
        self.assertEqual(event.state, "expired")
        self.assertFalse(event.identity_hash)

    def test_assignment_reply_and_blocked_reply_use_governed_command(self):
        self._receive()
        conversation = self._process().with_user(self.operator)
        conversation.action_assign_me()
        self.assertEqual(conversation.assigned_user_id, self.operator)
        with self.assertRaises(UserError):
            conversation.action_prepare_reply()
        self._draft()  # Verify and select the mock sender.
        action = conversation.action_prepare_reply()
        command = (
            self.env["omni.command"].browse(action["res_id"]).with_user(self.operator)
        )
        self.assertEqual(command.state, "draft")
        self.assertEqual(command.recipient, "12345")
        command.write({"body": "We will help."})
        command.action_submit()
        command.approval_request_id.with_user(self.approver).action_approve()
        command.action_enqueue_approved()
        consent = self.env["omni.consent"].create(
            {
                "channel_id": self.channel.id,
                "namespace": "bot-1",
                "recipient": "12345",
                "evidence": "Sandbox authorization",
            },
        )
        consent.with_user(self.manager).action_confirm()
        internal(self.channel).write({"dispatch_enabled": True})
        self._block().with_user(self.operator).action_block()
        self.assertFalse(self.env["omni.command"]._claim_next())
        self.assertEqual(command.state, "held")
        self.assertFalse(command.attempt_ids)
        with self.assertRaises(UserError):
            conversation.action_prepare_reply()

    def test_scope_and_rpc_guards(self):
        self._receive()
        conversation = self._process()
        for user in (self.outsider, self.portal):
            for row in (
                conversation,
                conversation.identity_id,
                conversation.message_ids,
                conversation.message_ids.revision_ids,
            ):
                with self.assertRaises(AccessError):
                    row.with_user(user).read()
        for row, vals in [
            (conversation, {"state": "closed"}),
            (self.endpoint, {"state": "enabled"}),
            (self.intake_policy, {"state": "active"}),
            (conversation.message_ids, {"body": "forged"}),
        ]:
            with self.assertRaises(AccessError):
                row.with_user(self.manager).write(vals)
        with self.assertRaises(AccessError):
            self.env["omni.webhook.event"].with_user(self.manager)._process_batch()
        with self.assertRaises(AccessError):
            self.env["omni.inbound.policy"].with_context(default_state="active").create(
                {"name": "forged", "channel_id": self.channel.id},
            )
        with self.assertRaises(AccessError):
            self.env["omni.identity"].with_user(self.manager).with_context(
                omni_internal=True,
            ).create(
                {
                    "channel_id": self.channel.id,
                    "namespace": "bot-1",
                    "external_key": "new",
                },
            )

    def test_rate_limit_is_persistent_and_no_payload_saved_on_rejection(self):
        internal(self.endpoint).write(
            {"ingress_window": fields.Datetime.now(), "ingress_count": 600},
        )
        with self.assertRaises(IngressRejected):
            self._receive()
        self.assertFalse(
            self.env["omni.webhook.event"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )

    def test_hold_preserves_preexisting_evidence_without_allowing_blocked_processing(self):
        event = self._receive()
        self.intake_policy.with_user(self.manager).action_toggle_legal_hold()
        self._block().with_user(self.operator).action_block()
        self.assertEqual(event.state, 'blocked')
        self.assertTrue(event.payload)
        self.assertFalse(self._process())
        with self.assertRaises(UserError):
            event.with_user(self.manager).action_replay()
        internal(event).write({'expires_at': fields.Datetime.now() - timedelta(seconds=1)})
        self.env['omni.webhook.event']._cron_retention()
        self.assertTrue(event.payload)
        self.intake_policy.with_user(self.manager).action_toggle_legal_hold()
        self.env['omni.webhook.event']._cron_retention()
        self.assertFalse(event.payload)
        self.assertEqual(event.state, 'expired')

    def test_expired_pending_content_retains_only_a_nonreplayable_tombstone(self):
        event = self._receive()
        internal(event).write({'expires_at': fields.Datetime.now() - timedelta(seconds=1)})
        self.assertFalse(self._process())
        self.assertEqual(event.state, 'expired')
        self.env['omni.webhook.event']._cron_retention()
        self.assertFalse(event.identity_hash)
        self.assertEqual(event.raw_hash, 'expired')
        self._receive()
        self.assertFalse(event.collision)
        self.assertFalse(event.payload)
        self.assertFalse(self._process())

    def test_policy_and_endpoint_defaults_fail_closed_without_adapter(self):
        self.endpoint.with_user(self.manager).action_disable()
        self.intake_policy.with_user(self.manager).action_pause()
        with patch('odoo.addons.omni_channel.models.inbox.get_adapter', return_value=HealthyAdapter()):
            with self.assertRaises(UserError):
                self.intake_policy.with_user(self.manager).action_activate()
            with self.assertRaises(UserError):
                self.endpoint.with_user(self.manager).action_enable()
        self.assertFalse(self.env.ref('omni_channel.cron_inbox').active)
        self.assertFalse(self.env.ref('omni_channel.cron_inbox_retention').active)

    def test_read_search_export_and_company_boundaries(self):
        self._receive()
        conversation = self._process()
        for user in (self.outsider, self.portal, self.env.ref('base.public_user')):
            with self.assertRaises((AccessError, UserError)):
                conversation.with_user(user).export_data(['thread_key'])
        self.assertFalse(self.env['omni.conversation'].with_user(self.outsider).search_count([]))
        with self.assertRaises(AccessError):
            conversation.with_user(self.operator).with_context(allowed_company_ids=[self.other_company.id]).read(['thread_key'])

    def test_reply_copy_preserves_context_and_incompatible_sender_is_blocked(self):
        self._receive()
        conversation = self._process().with_user(self.operator)
        self._draft()
        action = conversation.action_prepare_reply()
        command = self.env['omni.command'].browse(action['res_id']).with_user(self.operator)
        command.write({'body': 'Reviewed reply'})
        command.action_submit()
        self.assertEqual(command.payload['conversation']['thread'], conversation.thread_key)
        copied = command.copy()
        self.assertEqual(copied.conversation_id, conversation)
        with self.assertRaises(AccessError):
            command.copy({'state': 'approved'})
        account = self.account.copy({'external_account_key': 'second-bot', 'namespace': 'second-bot'})
        sender = self.env['omni.outbound.sender'].create({'name': 'Different bot', 'channel_id': self.channel.id,
            'account_id': account.id, 'external_key': 'second-bot'})
        with patch('odoo.addons.omni_channel.models.foundation.get_adapter', return_value=HealthyAdapter()):
            sender.with_user(self.manager).action_activate(self.channel.generation)
        with self.assertRaises(UserError):
            conversation.action_prepare_reply()
        with self.assertRaises(UserError):
            copied.action_submit()

    def test_existing_contact_link_is_explicit_and_does_not_expand_company_access(self):
        self._receive()
        conversation = self._process().with_user(self.operator)
        self.assertFalse(conversation.contact_name)
        partner = self.env['res.partner'].create({'name': 'Verified existing contact', 'company_id': self.company.id})
        other = self.env['res.partner'].create({'name': 'Other company contact', 'company_id': self.other_company.id})
        wizard = self.env['omni.contact.link'].with_user(self.operator).create({'identity_id': conversation.identity_id.id, 'partner_id': partner.id})
        count = self.env['res.partner'].search_count([])
        wizard.action_confirm()
        conversation.invalidate_recordset()
        self.assertEqual(conversation.contact_name, partner.display_name)
        self.assertEqual(conversation.action_open_contact()['res_id'], partner.id)
        self.assertEqual(self.env['res.partner'].search_count([]), count)
        with self.assertRaises(AccessError):
            self.env['omni.contact.link'].with_user(self.outsider).create({'identity_id': conversation.identity_id.id, 'partner_id': partner.id}).action_confirm()
        with self.assertRaises((AccessError, UserError)):
            self.env['omni.contact.link'].with_user(self.operator).create({'identity_id': conversation.identity_id.id, 'partner_id': other.id}).action_confirm()
        with self.assertRaises(AccessError):
            conversation.identity_id.read(['partner_id'])

    def test_private_thread_identity_mismatch_creates_no_new_identity(self):
        self._receive()
        conversation = self._process()
        event = self._receive(event_key='mismatch', sender_key='different-person', message_key='m-2')
        self._process()
        self.assertEqual(event.state, 'unresolved')
        self.assertEqual(event.reason_code, 'private_identity_mismatch')
        self.assertEqual(self.env['omni.identity'].search_count([('channel_id', '=', self.channel.id)]), 1)
        self.assertEqual(len(conversation.message_ids), 1)
