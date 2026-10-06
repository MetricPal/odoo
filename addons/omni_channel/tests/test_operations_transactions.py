"""Alert queue atomicity with independent PostgreSQL connections and real commits."""

import threading
import uuid
from unittest.mock import patch

from psycopg2.errors import SerializationFailure

from odoo import api, sql_db
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.omni_channel.models.command import internal


@tagged('post_install', '-at_install', 'omni_operations_transactions')
class TestOperationsTransactions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.database = sql_db.db_connect(self.cr.dbname)
        key = 'alert-transaction-' + uuid.uuid4().hex
        self.address = key + '@example.invalid'
        with self.database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            purpose = env['omni.purpose'].create({'name': key, 'code': key})
            channel = internal(env['omni.channel']).create({
                'name': key, 'purpose_id': purpose.id,
                'channel_type_id': env.ref('omni_channel.channel_type_telegram').id,
                'alerts_enabled': True, 'alerts_authorized_by': env.ref('base.user_admin').id,
                'alerts_addresses': self.address, 'failure_count': 5,
            })
            self.channel_id, self.purpose_id = channel.id, purpose.id
            cr.commit()
        self.addCleanup(self._cleanup)
        # Real authorization is covered in test_operations. These fixtures isolate
        # transaction behavior without granting/persisting user roles or cron activation.
        auth = patch.object(type(self.env['omni.channel']), '_validate_alert_authorization', return_value=None)
        auth.start()
        self.addCleanup(auth.stop)
        sending = patch.object(type(self.env['mail.mail']), 'send', side_effect=AssertionError('Unexpected transport'))
        sending.start()
        self.addCleanup(sending.stop)

    def _cleanup(self):
        with self.database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            cr.execute('UPDATE omni_channel SET alerts_last_mail_id = NULL WHERE id = %s', [self.channel_id])
            mails = env['mail.mail'].search([('email_to', '=', self.address)])
            messages = mails.mail_message_id
            mails.unlink()
            messages.exists().unlink()
            cr.execute('DELETE FROM omni_audit_event WHERE purpose_id = %s', [self.purpose_id])
            cr.execute('DELETE FROM omni_channel WHERE id = %s', [self.channel_id])
            cr.execute('DELETE FROM omni_purpose WHERE id = %s', [self.purpose_id])
            cr.commit()

    def _collect(self, cr):
        channel = api.Environment(cr, 1, {})['omni.channel'].browse(self.channel_id)
        channel._collect_operations_alert()
        return channel

    def _assert_durable(self, expected):
        with self.database.cursor() as cr:
            cr.execute('SELECT count(*) FROM mail_mail WHERE email_to = %s', [self.address])
            self.assertEqual(cr.fetchone()[0], expected)
            cr.execute("SELECT count(*) FROM omni_audit_event WHERE purpose_id = %s AND event = 'operations_alert_queued'", [self.purpose_id])
            self.assertEqual(cr.fetchone()[0], expected)
            cr.execute('SELECT alerts_snapshot, alerts_last_mail_id FROM omni_channel WHERE id = %s', [self.channel_id])
            snapshot, mail_id = cr.fetchone()
            self.assertEqual(bool(snapshot), bool(expected))
            self.assertEqual(bool(mail_id), bool(expected))

    def test_two_collectors_queue_one_alert_after_serialization_retry(self):
        started = threading.Event()
        outcomes, backend_pids = [], []

        def competitor(channel, cr):
            try:
                cr.execute("SET LOCAL statement_timeout = '5s'")
                cr.execute('SELECT pg_backend_pid(), alerts_snapshot FROM omni_channel WHERE id = %s', [self.channel_id])
                backend_pids.append(cr.fetchone()[0])
                started.set()
                try:
                    with mute_logger('odoo.sql_db'):
                        channel._collect_operations_alert()
                    outcomes.append('unexpected success')
                except SerializationFailure:
                    # Cursor cleanup runs on the parent test thread: Odoo's
                    # rollback refreshes the registry held by the test loader.
                    outcomes.append('serialization retry')
            except Exception as error:  # noqa: BLE001 - surface worker error in parent
                outcomes.append(repr(error))

        worker = None
        with self.database.cursor() as second:
            # The module test loader holds Registry._lock. Construct the isolated
            # environment here, then hand its cursor exclusively to the worker;
            # otherwise it waits on the test loader instead of PostgreSQL.
            second_channel = api.Environment(second, 1, {})['omni.channel'].browse(self.channel_id)
            try:
                with self.database.cursor() as first:
                    self._collect(first)
                    worker = threading.Thread(target=competitor, args=(second_channel, second), daemon=True)
                    worker.start()
                    self.assertTrue(started.wait(5))
                    blocked = False
                    for _ in range(50):
                        first.execute('SELECT cardinality(pg_blocking_pids(%s))', [backend_pids[0]])
                        if first.fetchone()[0]:
                            blocked = True
                            break
                        worker.join(0.02)
                    self.assertTrue(blocked, f'The second collector must contend on PostgreSQL: {outcomes}')
                    first.commit()
            finally:
                if worker and worker.ident:
                    worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, ['serialization retry'])
        # A later run uses a fresh transaction and sees the committed snapshot.
        with self.database.cursor() as cr:
            self._collect(cr)
            cr.commit()
        self._assert_durable(1)

    def test_failure_after_mail_creation_rolls_back_queue(self):
        def fail_audit(channel, event, detail):
            if channel.id == self.channel_id and event == 'operations_alert_queued':
                channel.env.flush_all()
                message = 'Synthetic failure after queue insert'
                raise RuntimeError(message)
            return original_audit(channel, event, detail)

        original_audit = type(self.env['omni.channel'])._audit
        with patch.object(type(self.env['omni.channel']), '_audit', fail_audit):
            with self.assertRaisesRegex(RuntimeError, 'after queue insert'), self.database.cursor() as cr:
                self._collect(cr)
        self._assert_durable(0)
        with self.database.cursor() as cr:
            self._collect(cr)
            cr.commit()
        self._assert_durable(1)

    def test_failure_after_snapshot_flush_rolls_back_everything(self):
        original_write = type(self.env['omni.channel']).write

        def fail_after_snapshot(channel, values):
            result = original_write(channel, values)
            if self.channel_id in channel.ids and 'alerts_snapshot' in values:
                channel.env.flush_all()
                message = 'Synthetic failure after snapshot flush'
                raise RuntimeError(message)
            return result

        with patch.object(type(self.env['omni.channel']), 'write', fail_after_snapshot):
            with self.assertRaisesRegex(RuntimeError, 'after snapshot flush'), self.database.cursor() as cr:
                self._collect(cr)
        self._assert_durable(0)
        with self.database.cursor() as cr:
            self._collect(cr)
            cr.commit()
        self._assert_durable(1)
