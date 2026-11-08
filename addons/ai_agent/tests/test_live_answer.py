from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..models import conversation
from ..models.common import internal
from ..services import hermes
from odoo.addons.mail.tests.common import mail_new_test_user


class FakeStream:
    """A streamed Hermes response: its lines, as urllib3 yields them."""

    def __init__(self, lines, status=200):
        self.status, self.lines, self.released = status, lines, False

    def __iter__(self):
        return iter(line.encode() + b'\n' for line in self.lines)

    def release_conn(self):
        self.released = True


@tagged('post_install', '-at_install')
class TestRunEvents(TransactionCase):
    """Hermes's live event stream of a run (GET /v1/runs/{id}/events)."""

    def _events(self, stream):
        pool = MagicMock()
        pool.request.return_value = stream
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443'}), \
                patch('odoo.addons.ai_agent.services.hermes.target',
                      return_value=(MagicMock(scheme='https', hostname='hermes.example.com',
                                              netloc='hermes.example.com'), ['93.184.216.34'], 443)), \
                patch('urllib3.HTTPSConnectionPool', return_value=pool):
            return list(hermes.run_events('https://hermes.example.com', '/p/sales/v1/runs/run_1/events',
                                          credential_value='k'))

    def test_the_stream_ends_with_the_run(self):
        stream = FakeStream([': keepalive', '', 'data: {"event": "run.started", "run_id": "run_1"}', '',
                             'data: {"event": "message.delta", "delta": "Hel"}', '',
                             'data: {"event": "run.completed", "run_id": "run_1"}', '',
                             'data: {"event": "never read"}'])
        self.assertEqual(self._events(stream), ['run.started', 'message.delta', 'run.completed'])
        self.assertTrue(stream.released)

    def test_a_refused_or_broken_stream_just_ends(self):
        self.assertEqual(self._events(FakeStream([], status=404)), [])
        self.assertEqual(self._events(FakeStream(['data: not json', '', ': stream closed'])), [])


@tagged('post_install', '-at_install')
class TestLiveAnswer(TransactionCase):
    """The answer is checked as soon as Hermes reports the end of the run."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.user = mail_new_test_user(cls.env, login='ai_live_staff', groups='ai_agent.group_user',
                                      company_ids=[Command.set(cls.env.company.ids)])
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Live engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Live assistant', 'engine_id': cls.engine.id,
                                               'user_ids': [Command.set(cls.user.ids)]})
        cls.agent.action_activate()

    def _queue(self, prompt='Summarize available knowledge'):
        return self.env['ai.agent.run'].with_user(self.user)._queue(self.agent.with_user(self.user), prompt)

    def test_a_submitted_run_is_followed_and_made_due_when_it_ends(self):
        run = self._queue().sudo()
        internal(run).write({'remote_id': 'run_live', 'state': 'running'})
        started = []
        with patch.object(conversation.odoo_module, 'current_test', None), \
                patch.object(conversation.threading, 'Thread',
                             lambda **kw: started.append(kw) or MagicMock()) as _thread:
            run._listen_for_end()
        self.assertEqual(len(started), 1, 'One listener per submitted run, started after commit')
        self.assertEqual(started[0]['args'][1], run.id)
        self.assertTrue(started[0]['args'][3].endswith('/v1/runs/run_live/events'))
        # Hermes reports the end: the run is due now and the scheduled check is woken.
        internal(run).write({'next_poll_at': '2099-01-01 00:00:00'})
        cron = self.env.ref('ai_agent.cron_runs')
        # The listener opens its own connection; here it uses the test's, which sees the test's records.
        registry = MagicMock()
        registry.return_value.cursor.return_value = nullcontext(self.env.cr)
        with patch.object(hermes, 'run_events', return_value=iter(['run.started', 'run.completed'])), \
                patch.object(conversation, 'Registry', registry), \
                patch.object(type(cron), '_trigger') as trigger:
            conversation._listen_for_end(self.env.cr.dbname, run.id, 'https://hermes.example.com',
                                         '/v1/runs/run_live/events', 'k', False)
        run.invalidate_recordset()
        self.assertLess(str(run.next_poll_at), '2099')
        trigger.assert_called_once()

    def test_no_listener_in_tests_or_when_hermes_has_no_stream(self):
        run = self._queue().sudo()
        internal(run).write({'remote_id': 'run_quiet', 'state': 'running'})
        with patch.object(conversation.threading, 'Thread') as thread:
            run._listen_for_end()
        thread.assert_not_called()
