"""Use separate committed PostgreSQL sessions, not shared test cursors."""

import threading
import uuid

from psycopg2.errors import UniqueViolation

from odoo import api, sql_db
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestOmniConcurrency(TransactionCase):
    def test_partial_unique_index_serializes_competing_selections(self):
        database = sql_db.db_connect(self.cr.dbname)
        key = 'concurrency-' + uuid.uuid4().hex
        ids = {}
        finished = threading.Event()
        started = threading.Event()
        results = []
        with database.cursor() as cr:
            env = api.Environment(cr, 1, {})
            purpose = env['omni.purpose'].create({'name': key, 'code': key})
            channel = env['omni.channel'].create(
                {
                    'name': key,
                    'purpose_id': purpose.id,
                    'channel_type_id': env.ref('omni_channel.channel_type_telegram').id,
                },
            )
            account = env['omni.account'].create(
                {
                    'name': key,
                    'purpose_id': purpose.id,
                    'channel_type_id': channel.channel_type_id.id,
                    'external_account_key': key,
                    'namespace': key,
                },
            )
            senders = env['omni.outbound.sender'].create(
                [
                    {
                        'name': key + str(i),
                        'channel_id': channel.id,
                        'account_id': account.id,
                        'external_key': str(i),
                    }
                    for i in (1, 2)
                ],
            )
            ids = {
                'senders': senders.ids,
                'account': account.id,
                'channel': channel.id,
                'purpose': purpose.id,
            }
            cr.commit()

        def competing_selection():
            with database.cursor() as other:
                other.execute("SET LOCAL lock_timeout = '5s'")
                started.set()
                try:
                    with mute_logger('odoo.sql_db'):
                        other.execute(
                            'UPDATE omni_outbound_sender SET is_selected = TRUE WHERE id = %s',
                            [ids['senders'][1]],
                        )
                    other.commit()
                    results.append('unexpected success')
                except UniqueViolation:
                    other.rollback()
                    results.append('unique violation')
                except Exception as error:  # noqa: BLE001 - propagate thread failure type to test assertion
                    other.rollback()
                    results.append(type(error).__name__)
                finally:
                    finished.set()

        worker = threading.Thread(target=competing_selection)
        try:
            with database.cursor() as first:
                first.execute(
                    'UPDATE omni_outbound_sender SET is_selected = TRUE WHERE id = %s',
                    [ids['senders'][0]],
                )
                worker.start()
                self.assertTrue(started.wait(3))
                self.assertFalse(
                    finished.wait(0.1),
                    'Competing selection should wait for the first transaction',
                )
                first.commit()
            self.assertTrue(finished.wait(6))
            worker.join(timeout=1)
            self.assertEqual(results, ['unique violation'])
            with database.cursor() as check:
                check.execute(
                    'SELECT count(*) FROM omni_outbound_sender WHERE channel_id = %s AND is_selected',
                    [ids['channel']],
                )
                self.assertEqual(check.fetchone()[0], 1)
        finally:
            if worker.ident:
                worker.join(timeout=6)
            with database.cursor() as cleanup:
                cleanup.execute(
                    'DELETE FROM omni_outbound_sender WHERE id = ANY(%s)',
                    [ids['senders']],
                )
                cleanup.execute(
                    'DELETE FROM omni_account WHERE id = %s', [ids['account']],
                )
                cleanup.execute(
                    'DELETE FROM omni_channel WHERE id = %s', [ids['channel']],
                )
                cleanup.execute(
                    'DELETE FROM omni_purpose WHERE id = %s', [ids['purpose']],
                )
                cleanup.commit()
