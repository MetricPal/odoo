from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models import conversation
from ..models.common import internal
from ..services import hermes


class AgentCase(TransactionCase):
    """One Hermes connection with two active agents."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                                'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        cls.user = mail_new_test_user(cls.env, login='ai_capacity', groups='ai_agent.group_user',
                                     company_ids=[Command.set(cls.env.company.ids)], notification_type='inbox')
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Capacity engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Busy assistant', 'engine_id': cls.engine.id,
                                               'user_ids': [Command.set(cls.user.ids)]})
        cls.agent.action_activate()
        cls.other_agent = cls.env['ai.agent'].create({'name': 'Second assistant', 'engine_id': cls.engine.id,
                                                     'user_ids': [Command.set(cls.user.ids)]})
        cls.other_agent.action_activate()

    def _queue(self, agent=None, prompt='What is waiting for me?', priority='interactive'):
        agent = agent or self.agent
        return self.env['ai.agent.run'].with_user(self.user)._queue(
            agent.with_user(self.user), prompt, priority=priority).sudo()

    def _dispatch(self, request):
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', side_effect=request) as remote, \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        return remote

    def _accept(self):
        counter = iter(range(1000))
        return lambda *args, **kwargs: {'run_id': 'run_%s' % next(counter)}



@tagged('post_install', '-at_install')
class TestCapacity(AgentCase):
    """The assistant serves many automations and people at once: questions wait for a free slot, never block."""

    def test_questions_past_the_limit_wait_instead_of_being_refused(self):
        runs = [self._queue(prompt='Question %s' % i) for i in range(4)]
        self.assertEqual(set(r.state for r in runs), {'queued'}, 'Nothing is refused while the queue has room')
        remote = self._dispatch(self._accept())
        self.assertEqual(remote.call_count, 2, 'Only the agent limit (2) is sent at once')
        self.assertEqual([r.state for r in runs], ['running', 'running', 'queued', 'queued'], 'Oldest first')
        internal(runs[0]).write({'state': 'completed', 'finished_at': fields.Datetime.now()})
        self._dispatch(self._accept())
        self.assertEqual(runs[2].state, 'running', 'A finished run frees its slot for the next one')
        self.assertEqual(runs[3].state, 'queued')

    def test_a_full_queue_and_the_daily_limit_still_refuse(self):
        with patch.object(conversation, 'QUEUE_MAX', 2):
            self._queue()
            self._queue()
            with self.assertRaises(UserError) as error:
                self._queue()
        self.assertIn('too many questions waiting', str(error.exception))
        self.agent.action_pause()
        self.agent.write({'max_requests_per_day': 3, 'max_requests_per_user_day': 0})
        self.agent.action_activate()
        self._queue()
        with self.assertRaises(UserError):
            self._queue()

    def test_the_connection_limit_is_shared_by_all_agents(self):
        self.engine.max_concurrent = 3
        mine = [self._queue(prompt='Mine %s' % i) for i in range(2)]
        theirs = [self._queue(self.other_agent, prompt='Theirs %s' % i) for i in range(2)]
        remote = self._dispatch(self._accept())
        self.assertEqual(remote.call_count, 3, 'Hermes caps runs per gateway, across every profile')
        self.assertEqual([r.state for r in mine + theirs], ['running', 'running', 'running', 'queued'])
        with self.assertRaises(ValidationError):
            self.engine.max_concurrent = 0

    def test_people_go_before_automations(self):
        batch = [self._queue(prompt='Batch %s' % i, priority='automation') for i in range(3)]
        person = self._queue(prompt='A person is waiting')
        self._dispatch(self._accept())
        self.assertEqual(person.state, 'running')
        self.assertEqual([r.state for r in batch], ['running', 'queued', 'queued'])
        with self.assertRaises(UserError):
            self._queue(priority='urgent')

    def test_hermes_busy_puts_the_question_back_in_the_queue(self):
        run = self._queue()
        busy = hermes.HermesBusy('Hermes is busy', retry_after=1)
        self._dispatch(busy)
        self.assertEqual(run.state, 'queued', 'Hermes accepted nothing: wait, never "needs manager check"')
        self.assertEqual(run.busy_retries, 1)
        self.assertFalse(run.started_at)
        self.assertGreater(run.next_poll_at, fields.Datetime.now())
        self.assertIn('busy', run.event_ids.mapped('kind'))
        remote = self._dispatch(self._accept())
        remote.assert_not_called()  # not due yet
        internal(run).write({'next_poll_at': False})
        self._dispatch(self._accept())
        self.assertEqual(run.state, 'running')
        self.assertEqual(len(run.event_ids.filtered(lambda e: e.kind == 'busy')), 1, 'Logged once, not per retry')

    def test_transport_turns_http_429_into_busy(self):
        pool = MagicMock()
        pool.request.return_value.status = 429
        pool.request.return_value.headers = {'Retry-After': '7'}
        pool.request.return_value.read.return_value = b'{"error": {"message": "Too many concurrent runs (max 2)"}}'
        with patch.object(hermes.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('10.0.0.5', 443))]), \
             patch.object(hermes.urllib3, 'HTTPSConnectionPool', return_value=pool):
            with self.assertRaises(hermes.HermesBusy) as error:
                hermes.request(self.engine.url, self.engine.secret_reference, 'POST', '/v1/runs', {})
        self.assertEqual(error.exception.retry_after, 7)

    def test_uncertain_runs_do_not_hold_a_slot(self):
        stuck = [self._queue(prompt='Stuck %s' % i) for i in range(2)]
        for run in stuck:
            internal(run).write({'state': 'uncertain'})
        fresh = self._queue()
        self._dispatch(self._accept())
        self.assertEqual(fresh.state, 'running')

    def test_a_stop_hermes_never_confirms_frees_the_slot(self):
        run = self._queue()
        internal(run).write({'state': 'stop_requested', 'remote_id': 'run_hung', 'stop_claimed': True,
                             'stop_sent_at': fields.Datetime.now() - timedelta(minutes=6)})
        remote = self._dispatch(lambda *a, **k: {'status': 'running'})
        remote.assert_not_called()
        self.assertEqual(run.state, 'cancelled')
        self.assertIn('did not confirm the stop', run.error_message)
        recent = self._queue()
        internal(recent).write({'state': 'stop_requested', 'remote_id': 'run_slow', 'stop_claimed': True,
                                'stop_sent_at': fields.Datetime.now()})
        self._dispatch(lambda *a, **k: {'status': 'running'})
        self.assertEqual(recent.state, 'stop_requested', 'A recent stop gets time to be confirmed')

    def test_a_question_that_waited_too_long_fails_with_a_reason(self):
        run = self._queue()
        self.env.cr.execute("UPDATE ai_agent_run SET create_date = now() at time zone 'UTC' - interval '31 minutes' "
                            "WHERE id = %s", [run.id])
        run.invalidate_recordset()
        internal(run).write({'next_poll_at': fields.Datetime.now() + timedelta(minutes=5)})
        self._dispatch(self._accept())
        self.assertEqual(run.state, 'failed')
        self.assertIn('No free slot on Hermes', run.error_message)

    def test_the_full_hermes_reason_is_kept(self):
        run = self._queue()
        internal(run).write({'remote_id': 'run_quota', 'state': 'running'})
        reason = ('Gemini HTTP 429 (RESOURCE_EXHAUSTED): You exceeded your current quota, please check your plan and '
                  'billing details. ' + 'x' * 400 + ' Quota exceeded for metric: generate_content_free_tier_requests, '
                  'limit: 0, model: gemini-2.5-pro')
        with patch.object(type(self.engine), '_request', return_value={'status': 'failed', 'error': {'message': reason}}):
            run._poll()
        self.assertEqual(run.state, 'failed')
        self.assertIn('limit: 0, model: gemini-2.5-pro', run.error_message)


@tagged('post_install', '-at_install')
class TestSharedService(AgentCase):
    """ADR 0014 phase 2: one entry point for every caller, automation outside personal limits, paused models."""

    def _ask(self, prompt='What changed today?', **kwargs):
        kwargs.setdefault('caller', 'home')
        return self.env['ai.agent.run'].with_user(self.user)._ask(self.agent.with_user(self.user), prompt,
                                                                  **kwargs).sudo()

    def test_every_run_says_who_asked(self):
        run = self._ask(caller='omnichannel')
        self.assertEqual((run.caller, run.priority, run.user_id), ('omnichannel', 'interactive', self.user))
        background = self._ask(caller='marketing', automation=True)
        self.assertEqual((background.caller, background.priority), ('marketing', 'automation'))
        with self.assertRaises(UserError):
            self._ask(caller='somewhere')

    def test_background_work_does_not_use_up_a_persons_questions(self):
        self.agent.action_pause()
        self.agent.write({'max_requests_per_day': 20, 'max_requests_per_user_day': 2})
        self.agent.action_activate()
        for i in range(3):
            self._ask('Background %s' % i, automation=True)
        self._ask('Mine 1')
        self._ask('Mine 2')
        with self.assertRaises(UserError) as error:
            self._ask('Mine 3')
        self.assertIn('daily limit of 2', str(error.exception))

    def test_a_used_up_model_is_paused_and_waiting_questions_fail_at_once(self):
        failed = self._ask('First')
        key = failed._model_key()  # the agent's model, else its profile's default model
        internal(failed).write({'remote_id': 'run_quota', 'state': 'running'})
        waiting = self._ask('Second')
        reason = ('Gemini HTTP 429 (RESOURCE_EXHAUSTED): Quota exceeded for metric: '
                  'generate_content_free_tier_requests, limit: 0, model: gemini-2.5-pro')
        with patch.object(type(self.engine), '_request', return_value={'status': 'failed', 'error': reason}):
            failed._poll()
        pause = self.env['ai.agent.model.pause'].search([('engine_id', '=', self.engine.id)])
        self.assertEqual(pause.model_key, key)
        self.assertIn('limit: 0', pause.reason)
        self.assertEqual(self.engine.paused_model_ids, pause, 'Shown on the connection while paused')
        self.assertIn('model_paused', failed.event_ids.mapped('kind'))
        remote = self._dispatch(self._accept())
        remote.assert_not_called()
        self.assertEqual(waiting.state, 'failed')
        self.assertIn('is paused until', waiting.error_message)
        self.assertIn('limit: 0', waiting.error_message, 'The reason travels with it')
        # The pause ends by itself.
        later = self._ask('Third')
        internal(pause).write({'until': fields.Datetime.now() - timedelta(minutes=1)})
        self.engine.invalidate_recordset(['paused_model_ids'])
        self.assertFalse(self.engine.paused_model_ids)
        self._dispatch(self._accept())
        self.assertEqual(later.state, 'running')

    def test_a_one_off_failure_does_not_pause_the_model(self):
        run = self._ask()
        internal(run).write({'remote_id': 'run_odd', 'state': 'running'})
        with patch.object(type(self.engine), '_request',
                          return_value={'status': 'failed', 'error': 'The tool call returned invalid JSON.'}):
            run._poll()
        self.assertFalse(self.env['ai.agent.model.pause'].search([('engine_id', '=', self.engine.id)]))

    def _manager(self):
        return mail_new_test_user(self.env, login='ai_capacity_manager', groups='ai_agent.group_manager',
                                  company_ids=[Command.set(self.env.company.ids)])

    def test_managers_resume_a_paused_model_but_never_pause_by_hand(self):
        run = self._ask()
        pause = self.env['ai.agent.model.pause']._pause(self.engine, run._model_key(), 60, 'limit: 0', run)
        manager = self._manager()
        with self.assertRaises(AccessError):
            self.env['ai.agent.model.pause'].with_user(manager).create({
                'engine_id': self.engine.id, 'model_key': 'x/y', 'until': fields.Datetime.now()})
        with self.assertRaises(AccessError):
            pause.with_user(manager).write({'until': fields.Datetime.now()})
        with self.assertRaises(AccessError):
            pause.with_user(self.user).action_resume()
        pause.with_user(manager).action_resume()
        self.assertFalse(run._model_pause())
        self.assertIn('model_resumed', run.event_ids.mapped('kind'), 'Resume is recorded on the run')

    def test_a_source_past_its_daily_limit_is_refused(self):
        self.agent.action_pause()
        self.env['ai.agent.caller.limit'].create({'agent_id': self.agent.id, 'caller': 'workflow', 'daily_limit': 2})
        self.agent.action_activate()
        self._ask(caller='workflow')
        self._ask(caller='workflow', automation=True)
        self._ask(caller='home')  # other sources are not limited by it
        limit = self.agent.caller_limit_ids
        self.assertEqual((limit.used_today, limit.reached, limit.reached_label), (2, True, 'reached'))
        with self.assertRaises(UserError) as error:
            self._ask(caller='workflow')
        self.assertIn("reached today's limit for Workflows (2)", str(error.exception))
        with self.assertRaises(UserError):
            limit.write({'daily_limit': 10})  # same rule as the other limits: pause first
        with self.assertRaises(AccessError):
            limit.with_user(self.user).write({'daily_limit': 10})

    def test_activity_shows_who_asked_how_long_and_how_full(self):
        busy = self._ask('Busy', caller='marketing', automation=True)
        internal(busy).write({'busy_retries': 1})
        running = self._ask('Running')
        internal(running).write({'state': 'running', 'started_at': fields.Datetime.now() - timedelta(seconds=42)})
        self.assertEqual(busy.status_label, 'Queued · Hermes busy')
        self.assertRegex(busy.waiting_label, r'^\d+:\d{2}$')
        self.assertEqual(running.status_label, 'Running')
        self.assertRegex(running.waiting_label, r'^started 0:4\d ago$')
        self.assertEqual(running.engine_id, self.engine)
        agent = self.agent.with_context(ai_agent_show_load=1)
        self.assertEqual(agent.display_name, 'Busy assistant · 1 of 2 at the same time')
        self.assertEqual(self.agent.display_name, 'Busy assistant', 'Only Activity shows the load')
        self.assertEqual((self.agent.queued_count, self.agent.queued_label), (1, '1 more question waits in the queue'))
        action = self.agent.action_view_queued()
        self.assertEqual(action['context']['search_default_agent_id'], self.agent.id)
        self.assertTrue(action['context']['search_default_queued'])
        self.assertIn('1 running · 1 queued · oldest waiting', self.engine.load_summary)
        self.assertEqual(self.engine.action_view_activity()['domain'], [('agent_id.engine_id', '=', self.engine.id)])
        manager = self._manager()
        self.assertTrue(self.env['ai.agent.run'].with_user(manager).search([('id', '=', busy.id)]))
        running.with_user(self.user).action_stop()
        self.assertEqual(running.state, 'stop_requested', 'Stop from the list line')
