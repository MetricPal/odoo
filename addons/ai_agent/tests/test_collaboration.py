import json
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.common import internal
from ..models.tools import ToolCallError


@tagged('post_install', '-at_install')
class TestAgentsTogether(TransactionCase):
    """ADR 0015: routing a question to the right agent, and one agent asking another."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.person = new_test_user(cls.env, 'together_person', name='Sara Ahmadi',
                                   groups='base.group_user,ai_agent.group_user')
        cls.outsider = new_test_user(cls.env, 'together_outsider', groups='base.group_user,ai_agent.group_user')
        sales, finance = cls.env['hr.department'].create([{'name': 'Sales'}, {'name': 'Finance'}])
        Agent = cls.env['ai.agent']
        # Only this test's agents answer (demo data may have a company-wide agent).
        Agent.search([('state', '=', 'active')]).action_pause()
        audience = {'user_ids': [Command.set((cls.person | cls.outsider).ids)]}
        cls.company = Agent.create({'name': 'Company Assistant', 'engine_id': cls.engine.id, **audience})
        cls.sales = Agent.create({'name': 'Sales coach', 'description': 'Discounts and orders',
                                  'engine_id': cls.engine.id, 'department_id': sales.id, **audience})
        cls.finance = Agent.create({'name': 'Finance helper', 'description': 'Invoices and payments',
                                    'engine_id': cls.engine.id, 'department_id': finance.id,
                                    'user_ids': [Command.set(cls.person.ids)]})
        cls.sales.may_ask_ids = cls.finance
        (cls.company | cls.sales | cls.finance).action_activate()
        cls.Run = cls.env['ai.agent.run'].with_user(cls.person)

    def _cron(self, request):
        with patch.object(type(self.engine), '_inspect', return_value=({}, [])), \
             patch.object(type(self.engine), '_request', side_effect=request) as remote, \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}), \
             patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=60):
            self.env['ai.agent.run']._cron_process()
        return remote

    def _finish(self, run, answer):
        internal(run).write({'remote_id': 'remote_%s' % run.id, 'state': 'running'})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': answer}), \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            run._poll()

    # -- routing --------------------------------------------------------------------------------------------
    def test_choose_for_me_asks_the_company_agent_then_the_chosen_one(self):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            router = self.Run._route('Can I give Acme 10% off?', caller='home').sudo()
        self.assertEqual((router.purpose, router.agent_id, router.caller), ('route', self.company, 'home'))
        payloads = []

        def accept(method, path, payload=None, headers=None, **kwargs):
            payloads.append(payload)
            return {'run_id': 'route_1'}
        self._cron(accept)
        payload = payloads[0]
        self.assertIn('ONE JSON object', payload['instructions'])
        self.assertNotIn('run_key', payload['instructions'], 'Choosing has no tools')
        listed = json.loads(payload['input'].split('ASSISTANTS (data):\n')[1].split('\n\nQUESTION')[0])
        self.assertEqual({row['id'] for row in listed}, {self.company.id, self.sales.id, self.finance.id})
        self._finish(router, 'Sure: {"agent": %s, "why": "discounts and orders"}' % self.sales.id)
        chosen = router.routed_run_id
        self.assertEqual((chosen.agent_id, chosen.user_id, chosen.prompt), (self.sales, self.person, router.prompt))
        self.assertEqual((chosen.routed_from_id, chosen.route_reason), (router, 'discounts and orders'))
        self.assertEqual(router._final_run(), chosen)

    def test_a_pick_outside_the_persons_assistants_is_refused(self):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            router = self.env['ai.agent.run'].with_user(self.outsider)._route('Show invoices', caller='home').sudo()
        self._finish(router, '{"agent": %s, "why": "invoices"}' % self.finance.id)  # outsider may not ask Finance
        self.assertEqual(router.state, 'failed')
        self.assertFalse(router.routed_run_id)
        self.assertIn('No assistant could be chosen', router.error_message)

    def test_one_assistant_needs_no_choosing_and_choosing_does_not_use_up_questions(self):
        lonely = new_test_user(self.env, 'together_lonely', groups='base.group_user,ai_agent.group_user')
        self.sales.action_pause()
        self.sales.user_ids |= lonely
        self.sales.action_activate()
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            run = self.env['ai.agent.run'].with_user(lonely)._route('Hello', caller='home').sudo()
        self.assertEqual((run.purpose, run.agent_id), ('answer', self.sales))
        self.company.action_pause()
        self.company.write({'max_requests_per_user_day': 1})
        self.company.action_activate()
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            self.Run._route('One', caller='home')
            self.Run._route('Two', caller='home')  # a route run is not one of the person's questions

    def test_no_company_agent_means_no_choose_for_me(self):
        self.company.action_pause()
        with self.assertRaises(UserError):
            self.Run._route('Hello', caller='home')

    # -- one agent asks another -----------------------------------------------------------------------------
    def _running_sales_run(self, question='Can I give Acme 10% off on S00042?'):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            run = self.Run._ask(self.sales.with_user(self.person), question, caller='chat').sudo()
        internal(run).write({'state': 'running', 'remote_id': 'remote_parent', 'started_at': fields.Datetime.now()})
        return run

    def test_ask_agent_asks_as_the_same_person_and_merges_the_answer(self):
        parent = self._running_sales_run()
        tools = self.env['ai.agent.tools']
        result = tools._tool_ask_agent(parent, {'agent': self.finance.id, 'question': 'Open invoices of Acme?'})
        child = parent.child_run_ids
        self.assertEqual(result['asked'], 'Finance helper')
        self.assertEqual((child.agent_id, child.user_id, child.caller), (self.finance, self.person, 'agent'))
        self.assertEqual(child.asked_by_label, 'Asked by Sales coach for Sara Ahmadi')
        with self.assertRaises(ToolCallError):
            tools._tool_ask_agent(parent, {'agent': self.company.id, 'question': 'Not on the list'})
        with self.assertRaises(UserError):
            child._ask_other_agent(self.sales, 'One level only')
        # The asking run ends first ("I asked Finance"): nobody sees that line; it waits for Finance.
        self._finish(parent, 'I asked Finance helper.')
        self.assertFalse(parent.followup_run_ids)
        self._finish(child, '2 overdue invoices: RM 4,200.')
        followup = parent.followup_run_ids
        self.assertEqual((followup.agent_id, followup.purpose, followup.conversation_id),
                         (self.sales, 'followup', parent.conversation_id))
        self.assertIn('2 overdue invoices', followup.prompt)
        self.assertEqual(parent._final_run(), followup)
        roles = {run.id: run.link_role for run in followup.with_context(ai_link_of=followup.id).linked_run_ids}
        self.assertEqual(roles[parent.id], 'Asked from')
        self.assertEqual(roles[child.id], 'Asked Finance helper')

    def test_ask_agent_never_widens_what_the_person_sees(self):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            parent = self.env['ai.agent.run'].with_user(self.outsider)._ask(
                self.sales.with_user(self.outsider), 'Discount?', caller='chat').sudo()
        internal(parent).write({'state': 'running', 'remote_id': 'remote_outsider'})
        with self.assertRaises(ToolCallError) as error:
            self.env['ai.agent.tools']._tool_ask_agent(parent, {'agent': self.finance.id, 'question': 'Invoices?'})
        self.assertIn('cannot be asked for this person', str(error.exception))
        self.assertFalse(parent.child_run_ids)

    def test_at_most_three_questions_and_the_list_is_in_the_instructions(self):
        parent = self._running_sales_run()
        for i in range(3):
            parent._ask_other_agent(self.finance, 'Question %s' % i)
        with self.assertRaises(UserError):
            parent._ask_other_agent(self.finance, 'A fourth')
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            payload, _hash = parent._prepare_payload('synthetic-run-key')
        self.assertIn('ask_agent tool', payload['instructions'])
        self.assertIn('%s: Finance helper' % self.finance.id, payload['instructions'])
        self.assertNotEqual(self.sales._configuration_hash(), self.company._configuration_hash())
