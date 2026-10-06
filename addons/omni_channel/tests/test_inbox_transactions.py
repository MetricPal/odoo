"""Independent PostgreSQL transactions prove intake dedup and suppression ordering."""

import json
import threading
import uuid
from unittest.mock import patch

from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo import api, sql_db
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from .test_inbox import MockInboundAdapter


@tagged("post_install", "-at_install")
class TestOmniInboxTransactions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.database = sql_db.db_connect(self.cr.dbname)
        self.key = "inbox-race-" + uuid.uuid4().hex
        for target in (
            "odoo.addons.omni_channel.models.inbox.get_adapter",
            "odoo.addons.omni_channel.providers.inbound.get_adapter",
        ):
            patcher = patch(target, return_value=MockInboundAdapter())
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            purpose = env["omni.purpose"].create({"name": self.key, "code": self.key})
            channel = env["omni.channel"].create(
                {
                    "name": self.key,
                    "purpose_id": purpose.id,
                    "channel_type_id": env.ref("omni_channel.channel_type_telegram").id,
                },
            )
            account = env["omni.account"].create(
                {
                    "name": self.key,
                    "purpose_id": purpose.id,
                    "channel_type_id": channel.channel_type_id.id,
                    "namespace": self.key,
                    "external_account_key": self.key,
                },
            )
            endpoint = env["omni.inbound.endpoint"].create(
                {
                    "name": self.key,
                    "channel_id": channel.id,
                    "account_id": account.id,
                    "external_key": self.key,
                },
            )
            policy = env["omni.inbound.policy"].create(
                {"name": self.key, "channel_id": channel.id},
            )
            # Fixture-only role bypass; model/HTTP suites cover real human roles.
            with patch.object(type(policy), "_require_manager", return_value=None):
                policy.action_activate()
            with patch.object(type(endpoint), "_require_manager", return_value=None):
                endpoint.action_enable()
            self.purpose_id, self.channel_id, self.account_id = (
                purpose.id,
                channel.id,
                account.id,
            )
            self.endpoint_id, self.company_id, self.policy_id = (
                endpoint.id,
                channel.company_id.id,
                policy.id,
            )
            cr.commit()
        self.addCleanup(self._cleanup)
        self.raw = json.dumps(
            {
                "events": [
                    {
                        "event_key": "race-event",
                        "endpoint_key": self.key,
                        "namespace": self.key,
                        "kind": "message",
                        "sender_key": "123",
                        "thread_key": "123",
                        "message_key": "message",
                        "body": "Concurrent verified input",
                        "occurred_at": "2026-10-06 10:00:00",
                    },
                ],
            },
        ).encode()

    def _receive(self, cr):
        return (
            api.Environment(cr, 1, {})["omni.inbound.endpoint"]
            .browse(self.endpoint_id)
            ._receive(self.raw, {"X-Test-Signature": "verified"})
        )

    def _cleanup(self):
        with self.database.cursor() as cr:
            cr.execute(
                "DELETE FROM omni_audit_event WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_message_revision WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "UPDATE omni_webhook_event SET message_id = NULL WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_message WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_conversation WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_identity WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_webhook_event WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_blocked_identity WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_inbound_endpoint WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_inbound_policy WHERE purpose_id = %s",
                [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_account WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute(
                "DELETE FROM omni_channel WHERE purpose_id = %s", [self.purpose_id],
            )
            cr.execute("DELETE FROM omni_purpose WHERE id = %s", [self.purpose_id])
            cr.commit()

    def test_simultaneous_duplicate_ingress_has_one_effect(self):
        started, finished = threading.Event(), threading.Event()
        results = []

        def contender():
            try:
                with self.database.cursor() as cr:
                    cr.execute("SET LOCAL lock_timeout = '5s'")
                    started.set()
                    try:
                        with mute_logger("odoo.sql_db"):
                            cr.execute(
                                """
                                INSERT INTO omni_webhook_event
                                  (endpoint_id, account_id, company_id, purpose_id, policy_id,
                                   ownership_version, event_hash, payload_hash, raw_hash, kind, state, expires_at)
                                VALUES (%s, %s, %s, %s, %s, 1, %s, 'duplicate', 'duplicate',
                                        'message', 'received', '2026-11-06')
                            """,
                                [
                                    self.endpoint_id,
                                    self.account_id,
                                    self.company_id,
                                    self.purpose_id,
                                    self.policy_id,
                                    event_hash,
                                ],
                            )
                        cr.commit()
                        results.append("unexpected insert")
                    except UniqueViolation:
                        cr.rollback()
                        results.append("duplicate rejected")
            except Exception as error:  # noqa: BLE001 - assert thread failure in parent
                results.append(type(error).__name__)
            finally:
                finished.set()

        worker = threading.Thread(target=contender)
        try:
            with self.database.cursor() as first:
                self._receive(first)
                first.execute(
                    "SELECT event_hash FROM omni_webhook_event WHERE endpoint_id = %s",
                    [self.endpoint_id],
                )
                event_hash = first.fetchone()[0]
                worker.start()
                self.assertTrue(started.wait(3))
                self.assertFalse(finished.wait(0.1), results)
                first.commit()
            self.assertTrue(finished.wait(6))
            self.assertEqual(results, ["duplicate rejected"])
            with self.database.cursor() as cr:
                env = api.Environment(cr, 1, {})
                env["omni.webhook.event"]._process_batch()
                env["omni.webhook.event"]._process_batch()
                self.assertEqual(
                    env["omni.webhook.event"].search_count(
                        [("endpoint_id", "=", self.endpoint_id)],
                    ),
                    1,
                )
                self.assertEqual(
                    env["omni.message"].search_count(
                        [("purpose_id", "=", self.purpose_id)],
                    ),
                    1,
                )
                cr.commit()
        finally:
            if worker.ident:
                worker.join(timeout=6)

    def test_stale_worker_snapshot_cannot_miss_committed_block(self):
        with self.database.cursor() as cr:
            self._receive(cr)
            cr.commit()
        with self.database.cursor() as stale:
            stale.execute(
                "SELECT id FROM omni_webhook_event WHERE endpoint_id = %s",
                [self.endpoint_id],
            )
            self.assertTrue(stale.fetchone())
            with self.database.cursor() as blocking:
                env = api.Environment(blocking, 1, {})
                channel = env["omni.channel"].browse(self.channel_id)
                block = env["omni.blocked.identity"].create(
                    {
                        "company_id": self.company_id,
                        "purpose_id": self.purpose_id,
                        "channel_type_id": channel.channel_type_id.id,
                        "namespace": self.key,
                        "external_key": "123",
                        "reason": "Concurrent withdrawal",
                    },
                )
                block.action_block()
                blocking.commit()
            with self.assertRaises(SerializationFailure), mute_logger("odoo.sql_db"):
                api.Environment(stale, 1, {})["omni.webhook.event"]._process_batch()
            stale.rollback()
        with self.database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            env["omni.webhook.event"]._process_batch()
            event = env["omni.webhook.event"].search(
                [("endpoint_id", "=", self.endpoint_id)],
            )
            self.assertEqual(event.state, "blocked")
            self.assertFalse(event.payload)
            self.assertFalse(
                env["omni.identity"].search_count(
                    [("purpose_id", "=", self.purpose_id)],
                ),
            )
