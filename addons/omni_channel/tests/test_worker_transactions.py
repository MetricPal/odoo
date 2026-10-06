"""Real commits/crash boundaries; authorization itself is covered in test_dispatch."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from odoo import api, fields, sql_db
from odoo.tests import TransactionCase, tagged

from odoo.addons.omni_channel.models.command import internal
from odoo.addons.omni_channel.providers.dispatch import DispatchResult


@tagged("post_install", "-at_install")
class TestOmniWorkerTransactions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.database = sql_db.db_connect(self.cr.dbname)
        key = "worker-" + uuid.uuid4().hex
        with self.database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            purpose = env["omni.purpose"].create({"name": key, "code": key})
            channel = env["omni.channel"].create(
                {
                    "name": key,
                    "purpose_id": purpose.id,
                    "channel_type_id": env.ref("omni_channel.channel_type_telegram").id,
                },
            )
            account = env["omni.account"].create(
                {
                    "name": key,
                    "purpose_id": purpose.id,
                    "channel_type_id": channel.channel_type_id.id,
                    "namespace": key,
                    "external_account_key": key,
                },
            )
            sender = env["omni.outbound.sender"].create(
                {
                    "name": key,
                    "channel_id": channel.id,
                    "account_id": account.id,
                    "external_key": key,
                },
            )
            command = internal(env["omni.command"]).create(
                {
                    "name": key,
                    "channel_id": channel.id,
                    "recipient": "sandbox",
                    "body": "Sandbox only",
                    "reason": "Transaction test",
                    "state": "queued",
                    "sender_id": sender.id,
                    "payload": {"operation": "message.send"},
                },
            )
            internal(channel).write({"dispatch_enabled": True})
            self.command_id, self.channel_id = command.id, channel.id
            self.sender_id, self.account_id, self.purpose_id = (
                sender.id,
                account.id,
                purpose.id,
            )
            cr.commit()
        self.addCleanup(self._cleanup_fixture)
        self.auth_patch = patch.object(
            type(self.env["omni.command"]),
            "_check_dispatch_authorization",
            return_value=None,
        )
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def _cleanup_fixture(self):
        # These committed records belong only to this disposable test fixture.
        with self.database.cursor() as cr:
            cr.execute(
                "DELETE FROM omni_audit_event WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "UPDATE omni_command SET current_attempt_id = NULL WHERE id = %s",
                [self.command_id],
            )
            cr.execute(
                "DELETE FROM omni_attempt WHERE command_id = %s", [self.command_id],
            )
            cr.execute("DELETE FROM omni_command WHERE id = %s", [self.command_id])
            cr.execute(
                "DELETE FROM omni_outbound_sender WHERE id = %s", [self.sender_id],
            )
            cr.execute("DELETE FROM omni_account WHERE id = %s", [self.account_id])
            cr.execute("DELETE FROM omni_channel WHERE id = %s", [self.channel_id])
            cr.execute("DELETE FROM omni_purpose WHERE id = %s", [self.purpose_id])
            cr.commit()

    def _run_worker(self):
        # Force independent physical cursors even under Odoo's test registry.
        with patch.object(
            type(self.env.registry), "cursor", side_effect=self.database.cursor,
        ):
            self.env["omni.command"]._cron_dispatch(limit=1)

    def _observe_send(self, claim):
        self.assertEqual(claim.command_id, self.command_id)
        with self.database.cursor() as cr:
            cr.execute(
                "SELECT state, current_attempt_id, lease_token FROM omni_command WHERE id = %s",
                [claim.command_id],
            )
            self.assertEqual(
                cr.fetchone(), ("dispatching", claim.attempt_id, claim.token),
            )
            cr.execute(
                "SELECT outcome FROM omni_attempt WHERE id = %s", [claim.attempt_id],
            )
            self.assertEqual(cr.fetchone(), ("dispatching",))
        return DispatchResult("accepted", provider_message_key="sandbox-committed")

    def test_worker_commits_before_transport_and_does_not_send_twice(self):
        with patch(
            "odoo.addons.omni_channel.models.dispatch.dispatch_claim",
            side_effect=self._observe_send,
        ) as send:
            self._run_worker()
            self._run_worker()
            self.assertEqual(send.call_count, 1)
        with self.database.cursor() as cr:
            cr.execute(
                "SELECT state, attempt_count FROM omni_command WHERE id = %s",
                [self.command_id],
            )
            self.assertEqual(cr.fetchone(), ("accepted", 1))

    def test_result_persistence_failure_recovers_unknown_without_resend(self):
        with patch(
            "odoo.addons.omni_channel.models.dispatch.dispatch_claim",
            side_effect=self._observe_send,
        ) as send:
            with patch.object(
                type(self.env["omni.command"]),
                "_finish_attempt",
                side_effect=RuntimeError("simulated database failure"),
            ):
                with self.assertRaises(RuntimeError):
                    self._run_worker()
            self._run_worker()
            with self.database.cursor() as cr:
                cr.execute(
                    "UPDATE omni_command SET lease_expires_at = %s WHERE id = %s",
                    [fields.Datetime.now() - timedelta(minutes=1), self.command_id],
                )
                cr.commit()
            self._run_worker()
            self.assertEqual(send.call_count, 1)
        with self.database.cursor() as cr:
            cr.execute(
                "SELECT state, attempt_count FROM omni_command WHERE id = %s",
                [self.command_id],
            )
            self.assertEqual(cr.fetchone(), ("unknown", 1))
            cr.execute(
                "SELECT outcome FROM omni_attempt WHERE command_id = %s",
                [self.command_id],
            )
            self.assertEqual(cr.fetchall(), [("unknown",)])

    def test_competing_claim_skips_locked_channel_and_rollback_releases_work(self):
        with self.database.cursor() as first:
            claim = api.Environment(first, 1, {})["omni.command"]._claim_next()
            self.assertEqual(claim.command_id, self.command_id)
            with self.database.cursor() as other:
                other.execute("SET LOCAL statement_timeout = '2s'")
                self.assertIsNone(
                    api.Environment(other, 1, {})["omni.command"]._claim_next(),
                )
            first.rollback()
        with patch(
            "odoo.addons.omni_channel.models.dispatch.dispatch_claim",
            side_effect=self._observe_send,
        ) as send:
            self._run_worker()
            self.assertEqual(send.call_count, 1)
        with self.database.cursor() as cr:
            cr.execute(
                "SELECT count(*) FROM omni_attempt WHERE command_id = %s",
                [self.command_id],
            )
            self.assertEqual(cr.fetchone(), (1,))
