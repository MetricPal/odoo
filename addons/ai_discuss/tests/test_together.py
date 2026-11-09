from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal


@tagged('post_install', '-at_install')
class TestAssistantsTogether(TransactionCase):
    """ADR 0015 in Discuss (approved board 20) and the agent avatar (owner, 2026-11-09)."""

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
        cls.person = new_test_user(cls.env, 'together_chat', name='Sara Ahmadi',
                                   groups='base.group_user,ai_agent.group_user')
        Agent = cls.env['ai.agent']
        Agent.search([('state', '=', 'active')]).action_pause()
        sales, finance = cls.env['hr.department'].create([{'name': 'Sales'}, {'name': 'Finance'}])
        audience = {'engine_id': cls.engine.id, 'user_ids': [Command.set(cls.person.ids)]}
        cls.company = Agent.create({'name': 'Company Assistant', **audience})
        cls.sales = Agent.create({'name': 'Sales coach', 'department_id': sales.id, **audience})
        cls.finance = Agent.create({'name': 'Finance helper', 'department_id': finance.id, **audience})
        cls.sales.may_ask_ids = cls.finance
        (cls.company | cls.sales | cls.finance).action_activate()

    def _finish(self, run, answer):
        internal(run).write({'remote_id': 'remote_%s' % run.id, 'state': 'running'})
        with patch.object(type(self.engine), '_request', return_value={'status': 'completed', 'output': answer}), \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            run._poll()

    def _messages(self, chat):
        return chat.sudo().message_ids.sorted('id')

    def test_agent_avatar_is_the_ai_agent_icon_with_its_initial(self):
        svg = self.sales.partner_id._avatar_generate_svg().decode()
        self.assertIn('>S</text>', svg)
        self.assertIn('#ffb855', svg, 'The sparkles of the AI Agent icon')
        self.assertNotIn('>AI<', svg)
        person_svg = self.person.partner_id._avatar_generate_svg().decode()
        self.assertNotIn('#ffb855', person_svg, 'People keep their usual avatar')

    def test_ask_an_assistant_lands_in_the_chosen_chat_with_a_note(self):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            wizard = self.env['ai.agent.route.ask'].with_user(self.person).create({'prompt': 'Discount for Acme?'})
            wizard.action_send()
        router = self.env['ai.agent.run'].sudo().search([('user_id', '=', self.person.id), ('purpose', '=', 'route')])
        self.assertEqual(router.caller, 'chat')
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            self._finish(router, '{"agent": %s, "why": "discounts and orders"}' % self.sales.id)
        chosen = router.routed_run_id
        chat = self.env['discuss.channel'].sudo().browse(chosen.origin_res_id)
        self.assertEqual((chosen.agent_id, chat.ai_agent_id), (self.sales, self.sales))
        bodies = self._messages(chat).mapped('body')
        self.assertIn('Chosen for you: Sales coach, for discounts and orders.', bodies[-2])
        self.assertIn('action-ai_discuss.action_route_change', bodies[-2])
        self.assertIn('Discount for Acme?', bodies[-1])
        # Change: the same question to another assistant.
        change = self.env['ai.agent.route.ask'].with_user(self.person).with_context(
            active_model='ai.agent.run', active_id=router.id).create({'agent_id': self.finance.id})
        self.assertEqual(change.prompt, 'Discount for Acme?')
        self.assertNotIn(self.sales, change.allowed_agent_ids)
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            change.action_send()
        self.assertTrue(self.env['ai.agent.run'].sudo().search([('agent_id', '=', self.finance.id),
                                                                ('prompt', '=', 'Discount for Acme?')]))

    def test_asking_another_agent_shows_a_line_then_one_merged_answer(self):
        chat = self.env['discuss.channel'].with_user(self.person)._ai_chat_for(self.sales.with_user(self.person))
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            parent = chat._ai_post_question('Can I give Acme 10% off?').sudo()
        internal(parent).write({'state': 'running', 'remote_id': 'remote_parent'})
        child = parent._ask_other_agent(self.finance, 'Open invoices of Acme?')
        line = self._messages(chat)[-1]
        self.assertIn('Sales coach is asking Finance helper about Open invoices of Acme?', line.body)
        self._finish(parent, 'I asked Finance helper.')
        self.assertNotIn('I asked Finance helper.', ''.join(self._messages(chat).mapped('body')))
        self._finish(child, '2 overdue invoices.')
        followup = parent.followup_run_ids
        self._finish(followup, 'Yes, if the overdue invoices are paid first.')
        bodies = ''.join(self._messages(chat).mapped('body'))
        self.assertIn('Yes, if the overdue invoices are paid first.', bodies)
        self.assertIn('Asked Finance helper', bodies)
        self.assertFalse(line.exists(), 'The asking line is replaced by the answer')
