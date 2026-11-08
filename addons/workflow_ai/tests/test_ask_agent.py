from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ai_agent.models.common import internal

from ..models.step import verdict


@tagged('post_install', '-at_install')
class TestAskAgentStep(TransactionCase):
    """ADR 0012 phase 5: a workflow step asks an agent, as the department's AI assistant, and waits for the answer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.engine = cls.env['ai.agent.engine'].create({
            'name': 'Workflow engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.hr = cls.env['hr.department'].create({'name': 'Workflow HR'})
        cls.hr.action_create_ai_assistant()
        cls.assistant = cls.hr.ai_assistant_user_id
        cls.agent = cls.env['ai.agent'].create({'name': 'HR policy helper', 'engine_id': cls.engine.id,
                                               'department_id': cls.hr.id, 'access_scope': 'users',
                                               'department_ids': [Command.set(cls.hr.ids)]})
        cls.agent.action_activate()
        cls.manager = cls.env.ref('base.user_admin')
        cls.wf_env = cls.env(user=cls.manager)
        cls.partner = cls.wf_env['res.partner'].create({'name': 'Leave requester'})
        cls.model = cls.env['ir.model']._get('res.partner')

    # -- helpers ---------------------------------------------------------------------------------------------------
    def flow(self, use='note', **step_values):
        flow = self.wf_env['workflow.definition'].create({'name': 'Leave triage', 'model_id': self.model.id})
        ask = self.wf_env['workflow.step'].create({
            'workflow_id': flow.id, 'name': 'Check the policy', 'kind': 'agent', 'sequence': 0,
            'ai_agent_id': self.agent.id, 'ai_answer_use': use,
            'ai_question': 'Does {name} follow the leave policy? Answer yes or no.', **step_values})
        return flow, ask

    def write_step(self, flow, value, sequence, **values):
        action = self.wf_env['ir.actions.server'].create({
            'name': f'Set {value}', 'model_id': self.model.id, 'state': 'object_write',
            'update_path': 'ref', 'value': value})
        return self.wf_env['workflow.step'].create({
            'workflow_id': flow.id, 'name': f'Set {value}', 'kind': 'action', 'sequence': sequence,
            'action_id': action.id, **values})

    def activate(self, flow):
        self.wf_env['workflow.test'].create({'workflow_id': flow.id, 'record_id': self.partner.id}).action_start()
        flow.action_activate()

    def start(self, flow):
        flow._trigger_records(self.partner)
        run = flow.run_ids.filtered(lambda r: not r.is_test)[:1]
        run._advance()
        return run

    def answer(self, workflow_run, text, state='completed'):
        agent_run = workflow_run.ai_run_id.sudo()
        internal(agent_run).write({'state': state, 'answer': text})
        agent_run._notify_origin()
        return agent_run

    # -- tests -----------------------------------------------------------------------------------------------------
    def test_the_assistant_is_asked_and_the_workflow_waits_for_the_answer(self):
        flow, _ask = self.flow()
        self.activate(flow)
        run = self.start(flow)
        self.assertEqual(run.state, 'waiting', run.error)
        agent_run = run.ai_run_id.sudo()
        self.assertEqual(agent_run.user_id, self.assistant, 'Asked by the assistant, not by the execution user')
        self.assertEqual((agent_run.origin_model, agent_run.origin_res_id), ('workflow.run', run.id))
        self.assertIn('Does Leave requester follow the leave policy?', agent_run.prompt)
        self.assertIn('Leave triage', agent_run.prompt)
        # The fallback check of a run still going keeps waiting.
        run._advance()
        self.assertEqual(run.state, 'waiting')
        self.answer(run, 'Yes. Ten days fit the policy.')
        self.assertEqual(run.state, 'done', run.error)
        note = self.partner.message_ids.filtered(lambda m: 'Ten days fit the policy' in (m.body or ''))
        self.assertEqual(note.author_id, self.assistant.partner_id)
        self.assertTrue(note.subtype_id == self.env.ref('mail.mt_note'))

    def test_the_answer_can_go_to_a_field(self):
        field = self.env['ir.model.fields']._get('res.partner', 'ref')
        flow, _ask = self.flow(use='field', ai_answer_field_id=field.id)
        self.activate(flow)
        run = self.start(flow)
        self.answer(run, 'Policy OK')
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'Policy OK')

    def test_the_answer_chooses_the_yes_or_no_path(self):
        flow, ask = self.flow(use='branch')
        yes = self.write_step(flow, 'yes-path', 10, end=True)
        no = self.write_step(flow, 'no-path', 20, end=True)
        ask.write({'next_id': yes.id, 'false_id': no.id})
        self.assertTrue(ask.splits)
        self.assertFalse(flow._validate())
        self.activate(flow)
        run = self.start(flow)
        self.answer(run, '**No** — the request overlaps a blocked period.')
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'no-path')
        self.assertEqual((verdict('Yes, fine'), verdict('no.'), verdict('Maybe')), (True, False, None))

    def test_an_unclear_or_missing_answer_follows_the_error_setting(self):
        flow, ask = self.flow(use='branch', on_error='stop')
        yes = self.write_step(flow, 'yes-path', 10, end=True)
        ask.write({'next_id': yes.id, 'false_id': yes.id})
        self.activate(flow)
        run = self.start(flow)
        self.answer(run, 'It depends.')
        self.assertEqual(run.state, 'failed')
        self.assertIn('did not start with Yes or No', run.error)

        flow2, _ask2 = self.flow(on_error='continue')
        self.activate(flow2)
        run2 = self.start(flow2)
        self.answer(run2, False, state='failed')
        self.assertEqual(run2.state, 'done', run2.error)
        self.assertIn('skipped', run2.log_ids.mapped('state'))

    def test_retry_asks_again(self):
        flow, _ask = self.flow(on_error='retry', max_attempts=2)
        self.activate(flow)
        run = self.start(flow)
        first = self.answer(run, False, state='failed')
        self.assertEqual(run.state, 'waiting')
        self.assertTrue(run.ai_run_id and run.ai_run_id != first, 'A new question was asked')
        self.answer(run, False, state='failed')
        self.assertEqual(run.state, 'failed', 'Stops after the maximum attempts')

    def test_setup_issues_and_review(self):
        flow, ask = self.flow()
        ask.ai_question = 'Is {no_such_field} fine?'
        self.assertTrue(any('no_such_field' in issue for issue in flow._validate()))
        ask.write({'ai_question': 'Fine?', 'ai_answer_use': 'field'})
        self.assertTrue(any('text field' in issue for issue in flow._validate()))
        ask.ai_answer_use = 'branch'
        self.assertTrue(any('If no' in issue for issue in flow._validate()))
        ask.ai_answer_use = 'note'
        lonely = self.env['ai.agent'].create({'name': 'No assistant', 'engine_id': self.engine.id,
                                         'access_scope': 'company'})
        ask.ai_agent_id = lonely
        self.assertTrue(any('no AI assistant user' in issue for issue in flow._validate()))
        ask.ai_agent_id = self.agent
        self.assertFalse(flow._validate())
        self.agent.action_archive()
        self.assertTrue(any('not active' in issue for issue in flow._validate()), 'An archived agent is flagged')
        self.agent.action_unarchive()
        self.agent.action_activate()
        self.assertFalse(flow._validate())
        card = ask._card()
        self.assertEqual(card['card_label'], 'ASK AGENT')
        self.assertEqual(card['card_hint'], 'HR policy helper · answer posted as a note')
        self.assertEqual(ask.ai_runs_as, self.assistant.name)
        # Changing the question changes what was reviewed: the active workflow must be activated again.
        before = flow._fingerprint()
        ask.ai_question = 'Fine, really?'
        self.assertNotEqual(flow._fingerprint(), before)

    def test_an_assistant_asks_only_the_agents_that_act_as_it(self):
        other_department = self.env['hr.department'].create({'name': 'Workflow Finance'})
        other = self.env['ai.agent'].create({'name': 'Finance helper', 'engine_id': self.engine.id,
                                            'department_id': other_department.id, 'access_scope': 'company'})
        other.action_activate()
        Agent = self.env['ai.agent'].with_user(self.assistant)
        self.assertEqual(Agent.search([]), self.agent, 'Not even company-wide agents of others')
        with self.assertRaises((AccessError, UserError)):
            self.env['ai.agent.run']._queue_for_record(other, 'Hello', self.partner)
        with self.assertRaises(UserError):
            self.env['ai.agent.run']._queue_for_record(self.agent, 'Hello', self.partner)

    def test_the_assistant_may_not_sign_in_and_runs_without_proposals(self):
        flow, _ask = self.flow()
        self.activate(flow)
        run = self.start(flow)
        agent_run = run.ai_run_id.sudo()
        self.assertNotIn('propose_note', agent_run._prepare_payload(run_key='k')[0]['instructions'])
        self.assertTrue(self.assistant.ai_assistant)
        self.assertEqual(self.assistant.group_ids & self.env.ref('base.group_system'), self.env['res.groups'])
