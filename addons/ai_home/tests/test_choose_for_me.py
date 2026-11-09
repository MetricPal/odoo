from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal


@tagged('post_install', '-at_install')
class TestChooseForMe(TransactionCase):
    """Home: "Choose for me", who answered and why (ADR 0015, approved board 19)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(engine).write({'state': 'ready'})
        cls.engine = engine
        cls.person = new_test_user(cls.env, 'home_choose', groups='base.group_user,ai_agent.group_user')
        Agent = cls.env['ai.agent']
        Agent.search([('state', '=', 'active')]).action_pause()
        hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        audience = {'engine_id': engine.id, 'user_ids': [Command.set(cls.person.ids)]}
        cls.company = Agent.create({'name': 'Company Assistant', **audience})
        cls.hr = Agent.create({'name': 'HR policy helper', 'department_id': hr.id, **audience})
        (cls.company | cls.hr).action_activate()
        cls.Home = cls.env['ai.home.item'].with_user(cls.person)

    def test_choose_for_me_then_answered_by(self):
        agents = self.Home._usable_agents()
        self.assertTrue(self.Home._can_route(agents))
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            asked = self.Home.ask_ai(False, 'Can I carry over leave?')
        self.assertFalse(asked['conversationId'])
        self.assertEqual(self.Home.get_ai_answer(asked['runId'])['state'], 'choosing')
        router = self.env['ai.agent.run'].sudo().browse(asked['runId'])
        internal(router).write({'remote_id': 'remote_router', 'state': 'running'})
        with patch.object(type(self.engine), '_request', return_value={
                'status': 'completed', 'output': '{"agent": %s, "why": "leave rules"}' % self.hr.id}), \
             patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            router._poll()
        result = self.Home.get_ai_answer(asked['runId'])
        self.assertEqual((result['state'], result['answeredBy'], result['why']),
                         ('queued', 'HR policy helper', 'leave rules'))
        self.assertEqual(result['answeredById'], self.hr.id)
        self.hr.action_pause()
        self.assertFalse(self.Home._can_route(self.Home._usable_agents()), 'One assistant: nothing to choose')
