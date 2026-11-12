from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal


@tagged('post_install', '-at_install')
class TestAssistantJobs(TransactionCase):
    """Assistant jobs, plan M4 (approved boards 11.1 to 11.3, 2026-11-12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.junior = new_test_user(cls.env, 'job_junior', groups='marketing_intel.group_mi_user,ai_agent.group_user')
        cls.senior = new_test_user(cls.env, 'job_senior', groups='marketing_intel_team.group_mi_senior')
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Jobs engine', 'url': 'https://hermes.example.com', 'secret_reference': 'AI_AGENT_SECRET_TEST',
            'management_url': 'https://hermes.example.com', 'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        marketing = cls.env['hr.department'].create({'name': 'Jobs marketing'})
        marketing.action_create_ai_assistant()
        cls.agent = cls.env['ai.agent'].create({'name': 'Marketing Assistant', 'engine_id': engine.id,
                                               'department_id': marketing.id,
                                               'user_ids': [Command.set([cls.junior.id])]})
        cls.agent.action_activate()
        cls.brand = cls.env['mi.brand'].create({'name': 'Jobs brand', 'offering': 'Plants', 'monthly_budget': 1000,
                                                'ai_agent_id': cls.agent.id})
        cls.Job = cls.env['mi.job']

    def _job(self, xmlid, **values):
        job = self.env.ref('marketing_intel_jobs.%s' % xmlid)
        job.write(dict({'owner_id': self.junior.id, 'brand_id': self.brand.id}, **values))
        job.action_switch_on()
        return job

    def _answer(self, run, text, state='completed', error=False):
        ai_run = run.ai_run_id.sudo()
        agent_internal(ai_run).write({'state': state, 'answer': text, 'error_message': error})
        ai_run._notify_origin()

    def test_ten_ready_made_jobs_start_off_and_switch_on(self):
        jobs = self.Job.search([('kind', '!=', False)])
        self.assertEqual(len(jobs.mapped('kind')), 10)
        self.assertEqual(set(jobs.mapped('state')), {'off'})
        self.assertEqual(set(jobs.mapped('role')), {'junior', 'senior', 'hod'})
        job = self._job('job_newsletter')
        self.assertEqual(job.state, 'on')
        self.assertEqual(job.health, 'healthy')
        self.assertTrue(job.next_run > fields.Datetime.now())
        self.assertEqual(job.next_run.weekday(), 4, 'the newsletter runs on Fridays')

    def test_switch_on_proposes_the_current_user_as_owner(self):
        job = self.env.ref('marketing_intel_jobs.job_campaigns_at_risk').with_user(self.senior)
        job.sudo().owner_id = False
        job.action_switch_on_dialog()
        self.assertEqual(job.owner_id, self.senior)
        self.assertEqual(job.state, 'off', 'only the dialog button switches it on')

    def test_schedule(self):
        job = self.env.ref('marketing_intel_jobs.job_social_posts')
        self.junior.tz = 'UTC'
        job.owner_id = self.junior
        monday_noon = datetime(2026, 11, 9, 12, 0)  # a Monday
        job.write({'frequency': 'weekly', 'weekday': '0', 'hour': 7})
        self.assertEqual(job._next_after(monday_noon), datetime(2026, 11, 16, 7, 0))
        job.write({'frequency': 'daily', 'hour': 18})
        self.assertEqual(job._next_after(monday_noon), datetime(2026, 11, 9, 18, 0))
        job.write({'frequency': 'monthly', 'month_day': 1, 'hour': 8})
        self.assertEqual(job._next_after(monday_noon), datetime(2026, 12, 1, 8, 0))
        job.write({'frequency': 'hourly'})
        self.assertEqual(job._next_after(monday_noon), datetime(2026, 11, 9, 13, 0))

    def test_the_schedule_is_in_the_owner_timezone(self):
        job = self.env.ref('marketing_intel_jobs.job_social_posts')
        self.junior.tz = 'Asia/Kuala_Lumpur'  # UTC+8
        job.write({'owner_id': self.junior.id, 'frequency': 'weekly', 'weekday': '0', 'hour': 7})
        monday_noon_utc = datetime(2026, 11, 9, 12, 0)
        self.assertEqual(job._next_after(monday_noon_utc), datetime(2026, 11, 15, 23, 0),
                         'Monday 07:00 in Kuala Lumpur is Sunday 23:00 UTC')

    def test_a_job_asks_the_assistant_and_prepares_a_draft_for_its_owner(self):
        job = self._job('job_newsletter')
        job.action_run_now()
        run = job.run_ids[:1]
        self.assertEqual(run.state, 'waiting')
        ai_run = run.ai_run_id.sudo()
        self.assertEqual(ai_run.caller, 'marketing')
        self.assertIn('SUBJECT', ai_run.prompt)
        self._answer(run, 'SUBJECT: Spring is here\n\nEvery plant is 20% off.\n\nSee you soon.')
        self.assertEqual(run.state, 'done')
        mailing = self.env['mailing.mailing'].browse(int(run.output_refs[0].split(',')[1]))
        self.assertEqual(mailing.subject, 'Spring is here')
        self.assertEqual(mailing.state, 'draft', 'jobs only prepare, never send')
        self.assertEqual(job.health, 'waiting', 'the owner has a to-do from the result')
        self.assertEqual(run.activity_id.user_id, self.junior)
        run.activity_id.action_feedback()
        job.invalidate_recordset(['health'])  # as a new request would
        self.assertEqual(job.health, 'healthy')

    def test_two_failed_runs_make_the_job_failing_with_a_todo(self):
        job = self._job('job_social_posts')  # no connected social account
        job.action_run_now()
        job.action_run_now()
        runs = job.run_ids
        self.assertEqual(set(runs.mapped('state')), {'failed'})
        self.assertIn('No social account is connected', runs[0].error)
        self.assertEqual(job.health, 'failing')
        self.assertIn('No social account', job.last_error)
        self.assertTrue(job.activity_ids.filtered(lambda a: 'is failing' in (a.summary or '')))

    def test_the_answer_failing_fails_the_run(self):
        job = self._job('job_performance_summary')
        job.action_run_now()
        run = job.run_ids[:1]
        self._answer(run, False, state='failed', error='Model quota exhausted')
        self.assertEqual(run.state, 'failed')
        self.assertEqual(run.error, 'Model quota exhausted')

    def test_budget_burn_needs_no_assistant(self):
        today = fields.Date.context_today(self.env['mi.job'])
        plan = self.env['mi.plan'].create({'name': 'Burning', 'brand_id': self.brand.id, 'budget': 1000,
                                           'date_start': today - timedelta(days=5),
                                           'date_end': today + timedelta(days=45)})
        plan.sudo().write({'state': 'live'})
        self.env['mi.plan.spend'].create({'plan_id': plan.id, 'name': 'Ads', 'amount': 900})
        job = self._job('job_budget_burn')
        job.action_run_now()
        run = job.run_ids[:1]
        self.assertEqual(run.state, 'done')
        self.assertFalse(run.ai_run_id)
        self.assertIn('1', run.result)
        self.assertEqual(job.health, 'waiting')

    def test_daily_ai_limit(self):
        job = self._job('job_performance_summary', ai_daily_limit=1)
        job.action_run_now()
        job.action_run_now()
        newest = job.run_ids.sorted('id')[-1]
        self.assertEqual(newest.state, 'failed')
        self.assertIn("AI limit", newest.error)

    def test_juniors_see_their_own_jobs_and_the_ready_made_ones(self):
        mine = self._job('job_newsletter')
        theirs = self._job('job_performance_summary', owner_id=self.senior.id)
        visible = self.Job.with_user(self.junior).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)
        self.assertIn(self.env.ref('marketing_intel_jobs.job_budget_burn'), visible, 'ready-made jobs to switch on')
        self.assertIn(theirs, self.Job.with_user(self.senior).search([]), 'seniors see every job')

    def test_the_panel_block_lists_the_jobs(self):
        job = self._job('job_newsletter')
        block = self.env['mi.panel']._block_automation_health(self.brand, self.env['mi.plan'])
        self.assertEqual(block['action'], 'marketing_intel_jobs.action_jobs')
        self.assertIn(job.name, [row['title'] for row in block['rows']])
