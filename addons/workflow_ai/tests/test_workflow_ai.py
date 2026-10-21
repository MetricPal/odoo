from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_agent.models.common import internal


@tagged('post_install', '-at_install')
class TestWorkflowAiDraft(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.admin = cls.env.ref('base.user_admin')
        cls.admin.write({'group_ids': [Command.link(cls.env.ref('ai_agent.group_user').id)]})
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Draft engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Workflow drafter', 'engine_id': engine.id,
                                               'user_ids': [Command.set(cls.admin.ids)]})
        cls.agent.action_activate()
        cls.model = cls.env['ir.model']._get('res.partner')

    def _draft(self):
        Workflow = self.env['workflow.definition'].with_user(self.admin)
        action = Workflow.ai_draft('Remind the salesperson when a contact has no activity for a week',
                                   self.model.id, self.agent.id)
        workflow = Workflow.browse(action['params']['workflow_id'])
        return workflow, workflow.ai_run_id.sudo()

    def _finish(self, run, answer, state='completed'):
        internal(run).write({'state': state, 'answer': answer})
        run._notify_origin()

    def test_agents_are_offered_and_a_draft_is_created(self):
        data = self.env['workflow.definition'].with_user(self.admin).home_data()
        self.assertIn(self.agent.id, [agent['id'] for agent in data['agents']])
        self.assertTrue(data['ai_drafting'])
        workflow, run = self._draft()
        self.assertEqual(workflow.state, 'draft')
        self.assertEqual(run.origin_model, 'workflow.definition')
        self.assertIn('Reply with one JSON object only', run.prompt)
        self.assertFalse(workflow.builder_data()['ai']['done'])

    def test_proposal_fills_name_trigger_and_steps_only(self):
        workflow, run = self._draft()
        self._finish(run, 'Here: {"name": "Idle contact reminder", "trigger": "schedule", '
                          '"steps": ["Find contacts without activity", "Create a to-do for the salesperson"]}')
        self.assertEqual(workflow.name, 'Idle contact reminder')
        self.assertEqual(workflow.trigger, 'schedule')
        self.assertEqual(workflow.ai_suggestion,
                         '1. Find contacts without activity\n2. Create a to-do for the salesperson')
        self.assertFalse(workflow.step_ids, 'The agent proposes; the administrator builds')
        self.assertEqual(workflow.state, 'draft')
        info = workflow.builder_data()['ai']
        self.assertTrue(info['done'])

    def test_unusable_answers_and_failures_are_shown_not_applied(self):
        workflow, run = self._draft()
        self._finish(run, '{"trigger": "delete_everything", "name": ""} plus some prose')
        self.assertEqual(workflow.trigger, 'manual')
        self.assertTrue(workflow.ai_suggestion)
        other, failed = self._draft()
        self._finish(failed, False, state='failed')
        self.assertIn('without an answer', other.ai_suggestion)
