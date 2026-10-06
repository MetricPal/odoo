from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .test_commands import TestOmniCommands
from .test_foundation import HealthyAdapter
from odoo.addons.omni_channel.models.command import internal
from odoo.addons.omni_channel.providers.dispatch import DispatchResult, dispatch_claim


class MockDispatchAdapter(HealthyAdapter):
    dispatch_supported = True

    def validate_command(self, payload, config):
        return payload["operation"] == "message.send"

    def dispatch(self, claim):
        return DispatchResult("accepted", provider_message_key="mock-123")


@tagged("post_install", "-at_install")
class TestOmniDispatch(TestOmniCommands):
    def _queued(self, consent=True):
        command = self._draft()
        command.action_submit()
        command.approval_request_id.with_user(self.approver).action_approve()
        command.action_enqueue_approved()
        internal(self.channel).write({"dispatch_enabled": True})
        if consent:
            grant = self.env["omni.consent"].create(
                {
                    "channel_id": self.channel.id,
                    "namespace": self.account.namespace,
                    "recipient": command.recipient,
                    "evidence": "Explicit sandbox recipient authorization.",
                },
            )
            grant.with_user(self.manager).action_confirm()
        return command.sudo()

    def _claim(self):
        return self.env["omni.command"]._claim_next()

    def test_success_records_one_attempt_and_fences_duplicate_result(self):
        command = self._queued()
        claim = self._claim()
        self.assertEqual(command.state, "dispatching")
        self.assertEqual(claim.command_uuid, command.uuid)
        with patch(
            "odoo.addons.omni_channel.providers.dispatch.get_adapter",
            return_value=MockDispatchAdapter(),
        ):
            result = dispatch_claim(claim)
        self.assertTrue(command._finish_attempt(claim, result))
        self.assertEqual(command.state, "accepted")
        self.assertEqual(command.provider_message_key, "mock-123")
        self.assertEqual(command.current_attempt_id.outcome, "accepted")
        self.assertFalse(command._finish_attempt(claim, DispatchResult("unknown")))
        self.assertEqual(command.state, "accepted")
        self.assertFalse(self._claim())

    def test_timeout_is_unknown_and_cannot_retry_cancel_or_switch_sender(self):
        command = self._queued()
        claim = self._claim()
        adapter = MockDispatchAdapter()
        adapter.dispatch = lambda _claim: (_ for _ in ()).throw(
            TimeoutError("SECRET_FROM_PROVIDER"),
        )
        with patch(
            "odoo.addons.omni_channel.providers.dispatch.get_adapter",
            return_value=adapter,
        ):
            command._finish_attempt(claim, dispatch_claim(claim))
        self.assertEqual(command.state, "unknown")
        self.assertFalse(self._claim())
        with self.assertRaises(UserError):
            command.with_user(self.operator).action_cancel()
        with self.assertRaises(UserError):
            self.sender.with_user(self.manager).action_deactivate()
        with self.assertRaises(UserError):
            self.sender.with_user(self.manager).action_activate(self.channel.generation)
        self.assertNotIn("SECRET_FROM_PROVIDER", command.held_reason)
        self.assertFalse(
            self.env["omni.audit.event"].search(
                [("detail", "ilike", "SECRET_FROM_PROVIDER")],
            ),
        )

    def test_definite_no_send_obeys_retry_after_and_budget(self):
        command = self._queued()
        now = fields.Datetime.now()
        for index in range(5):
            now += timedelta(minutes=2)
            with patch(
                "odoo.addons.omni_channel.models.dispatch.fields.Datetime.now",
                return_value=now,
            ):
                claim = self._claim()
                self.assertTrue(claim)
                command._finish_attempt(
                    claim,
                    DispatchResult(
                        "definitely_not_sent",
                        retryable=True,
                        retry_after=60,
                        reason_code="rate_limited",
                    ),
                )
                self.assertEqual(command.attempt_count, index + 1)
                if index < 4:
                    self.assertEqual(command.state, "queued")
                    self.assertGreaterEqual(
                        command.next_attempt_at, now + timedelta(seconds=60),
                    )
                    self.assertFalse(self._claim())
        self.assertEqual(command.state, "failed")
        self.assertEqual(len(command.attempt_ids), 5)
        self.assertFalse(self._claim())

    def test_missing_or_revoked_consent_holds_before_provider_invocation(self):
        command = self._queued(consent=False)
        self.assertFalse(self._claim())
        self.assertEqual(command.state, "held")
        self.assertEqual(command.attempt_count, 0)

    def test_consent_withdrawal_after_approval_is_enforced(self):
        command = self._queued()
        grant = self.env["omni.consent"].search([("channel_id", "=", self.channel.id)])
        grant.with_user(self.manager).action_revoke()
        self.assertFalse(self._claim())
        self.assertEqual(command.state, "held")

    def test_pause_stops_new_claims_but_preserves_inflight_result(self):
        command = self._queued()
        self.channel.with_user(self.manager).action_pause_dispatch()
        self.assertFalse(self._claim())
        self.assertEqual(command.state, "queued")
        internal(self.channel).write({"dispatch_enabled": True})
        claim = self._claim()
        self.channel.with_user(self.manager).action_pause_dispatch()
        command._finish_attempt(
            claim, DispatchResult("accepted", provider_message_key="accepted-inflight"),
        )
        self.assertEqual(command.state, "accepted")
        self.assertFalse(self.channel.dispatch_enabled)

    def test_expired_lease_recovers_unknown_and_late_worker_cannot_overwrite(self):
        command = self._queued()
        claim = self._claim()
        future = fields.Datetime.now() + timedelta(minutes=3)
        with patch(
            "odoo.addons.omni_channel.models.dispatch.fields.Datetime.now",
            return_value=future,
        ):
            self.assertEqual(self.env["omni.command"]._recover_expired(), 1)
        self.assertEqual(command.state, "unknown")
        self.assertEqual(command.current_attempt_id.reason_code, "lease_expired")
        self.assertFalse(
            command._finish_attempt(
                claim, DispatchResult("accepted", provider_message_key="late"),
            ),
        )
        self.assertEqual(command.state, "unknown")
        self.assertFalse(self._claim())

    def test_forged_lease_cannot_complete_attempt(self):
        command = self._queued()
        claim = self._claim()
        self.assertFalse(
            command._finish_attempt(
                replace(claim, token="forged"),
                DispatchResult("accepted", provider_message_key="fake"),
            ),
        )
        self.assertEqual(command.state, "dispatching")

    def test_reconciliation_preserves_original_evidence_and_never_resends(self):
        command = self._queued()
        claim = self._claim()
        command._finish_attempt(claim, DispatchResult("unknown"))
        wizard = (
            self.env["omni.reconciliation"]
            .with_user(self.manager)
            .create(
                {
                    "command_id": command.id,
                    "outcome": "not_sent",
                    "evidence": "Provider administrator verified absence using its request log.",
                },
            )
        )
        wizard.action_confirm()
        self.assertEqual(command.state, "failed")
        self.assertEqual(command.current_attempt_id.outcome, "unknown")
        self.assertFalse(self._claim())
        self.sender.with_user(self.manager).action_deactivate()
        self.assertFalse(self.sender.is_selected)

    def test_reconciliation_requires_manager_evidence_and_provider_id(self):
        command = self._queued()
        claim = self._claim()
        command._finish_attempt(claim, DispatchResult("unknown"))
        with self.assertRaises(AccessError):
            command.with_user(self.operator).action_open_reconciliation()
        with self.assertRaises(AccessError):
            command.with_user(self.outsider).action_open_reconciliation()
        wizard = (
            self.env["omni.reconciliation"]
            .with_user(self.manager)
            .create(
                {
                    "command_id": command.id,
                    "outcome": "accepted",
                    "evidence": "Verified acceptance in provider log.",
                },
            )
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.provider_message_key = "verified-123"
        wizard.action_confirm()
        self.assertEqual(command.provider_message_key, "verified-123")
        self.assertEqual(command.state, "accepted")

    def test_dispatch_controls_and_evidence_are_not_rpc_writable(self):
        command = self._queued()
        claim = self._claim()
        with self.assertRaises(AccessError):
            self.channel.with_user(self.manager).write({"dispatch_enabled": True})
        with self.assertRaises(AccessError):
            command.with_user(self.operator).write({"lease_token": "forged"})
        with self.assertRaises(AccessError):
            command.current_attempt_id.with_user(self.manager).write(
                {"outcome": "accepted"},
            )
        with self.assertRaises(AccessError):
            command.current_attempt_id.with_context(_omni_internal=True).write(
                {"outcome": "accepted"},
            )
        with self.assertRaises(AccessError):
            self.env["omni.command"].with_user(self.manager)._claim_next()
        command._finish_attempt(
            claim, DispatchResult("accepted", provider_message_key="real"),
        )
        with self.assertRaises(AccessError):
            internal(command.current_attempt_id).write({"reason_code": "changed"})

    def test_stale_approval_and_inactive_requester_hold_without_attempt(self):
        command = self._queued()
        self.operator.active = False
        self.assertFalse(self._claim())
        self.assertEqual(command.state, "held")
        self.assertFalse(command.attempt_ids)

    def test_expired_approval_never_claims(self):
        command = self._queued()
        with patch(
            "odoo.addons.omni_channel.models.dispatch.fields.Datetime.now",
            return_value=command.expires_at + timedelta(seconds=1),
        ):
            self.assertFalse(self._claim())
        self.assertEqual(command.state, "expired")

    def test_bad_adapter_result_never_becomes_retryable(self):
        command = self._queued()
        claim = self._claim()
        adapter = MockDispatchAdapter()
        adapter.dispatch = lambda _: {
            "outcome": "accepted",
            "secret": "SHOULD_NOT_PERSIST",
        }
        with patch(
            "odoo.addons.omni_channel.providers.dispatch.get_adapter",
            return_value=adapter,
        ):
            command._finish_attempt(claim, dispatch_claim(claim))
        self.assertEqual(command.state, "unknown")
        self.assertFalse(command.provider_message_key)

    def test_failed_preflight_never_invokes_transport(self):
        command = self._queued()
        claim = self._claim()
        adapter = MockDispatchAdapter()
        adapter.validate_command = lambda *_: False
        with (
            patch.object(adapter, "dispatch") as send,
            patch(
                "odoo.addons.omni_channel.providers.dispatch.get_adapter",
                return_value=adapter,
            ),
        ):
            command._finish_attempt(claim, dispatch_claim(claim))
        send.assert_not_called()
        self.assertEqual(command.state, "failed")
        self.assertEqual(command.current_attempt_id.outcome, "definitely_not_sent")

    def test_circuit_breaker_pauses_without_switching_sender(self):
        command = self._queued()
        now = fields.Datetime.now()
        for _index in range(5):
            now += timedelta(seconds=50)
            with patch(
                "odoo.addons.omni_channel.models.dispatch.fields.Datetime.now",
                return_value=now,
            ):
                claim = self._claim()
                self.assertTrue(claim)
                command._finish_attempt(
                    claim,
                    DispatchResult(
                        "definitely_not_sent", retryable=True, reason_code="transport",
                    ),
                )
        self.assertGreater(self.channel.circuit_until, now)
        self.assertEqual(self.channel.failure_count, 5)
        self.assertTrue(self.sender.is_selected)

    def test_attempt_and_recipient_evidence_obey_scope(self):
        command = self._queued()
        self._claim()
        with self.assertRaises(AccessError):
            command.current_attempt_id.with_user(self.outsider).read(["outcome"])
        consent = self.env["omni.consent"].search(
            [("channel_id", "=", self.channel.id)],
        )
        with self.assertRaises(AccessError):
            consent.with_user(self.outsider).read(["evidence"])
        with self.assertRaises(AccessError):
            consent.with_user(self.operator).action_revoke()
        with self.assertRaises(AccessError):
            consent.with_user(self.manager).write({"recipient": "another-person"})

    def test_disabled_cron_and_channel_are_install_defaults(self):
        self.assertFalse(self.env.ref("omni_channel.cron_dispatch").active)
        self.assertFalse(self.channel.dispatch_enabled)
