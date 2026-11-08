from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal
from odoo.addons.ai_discuss import _post_init


@tagged('post_install', '-at_install')
class TestAgentChatPartner(TransactionCase):
    """ADR 0013 phase 1: each agent has its own chat partner; OdooBot is untouched."""

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
        cls.person = new_test_user(cls.env, 'discuss_person', groups='base.group_user,ai_agent.group_user')

    def _agent(self, name='Recruitment screener', **values):
        return self.env['ai.agent'].create({'name': name, 'engine_id': self.engine.id,
                                            'user_ids': [Command.set(self.person.ids)], **values})

    def _mentions(self, search):
        store = self.env['res.partner'].with_user(self.person).get_mention_suggestions(search)
        return [row.get('name') for row in store._build_result().get('res.partner', [])]

    def test_every_agent_gets_its_own_archived_chat_partner(self):
        agent = self._agent()
        partner = agent.partner_id
        self.assertTrue(partner, 'Created with the agent')
        self.assertEqual((partner.name, partner.active, partner.ai_agent_partner), ('Recruitment screener', False, True))
        self.assertFalse(partner.user_ids, 'Never a user: nobody can log in as it')
        self.assertNotIn(partner, self.env['res.partner'].search([]), 'Not in Contacts')
        self.assertNotEqual(partner, self.env.ref('base.partner_root'), 'OdooBot stays the system voice')
        agent.name = 'Applicant screener'
        self.assertEqual(partner.name, 'Applicant screener', 'Follows the agent name')
        other = self._agent('Sales coach')
        self.assertNotEqual(other.partner_id, partner, 'One partner per agent')

    def test_agents_made_before_the_module_get_a_partner(self):
        agent = self._agent()
        partner = agent.partner_id
        internal(agent.sudo()).write({'partner_id': False})
        _post_init(self.env)
        self.assertTrue(agent.partner_id)
        self.assertNotEqual(agent.partner_id, partner)
        _post_init(self.env)
        self.assertEqual(len(self.env['res.partner'].with_context(active_test=False).search(
            [('name', '=', agent.name), ('ai_agent_partner', '=', True)])), 2, 'Nothing created twice')

    def test_an_unused_agent_deleted_takes_its_partner_along(self):
        agent = self._agent('Never used')
        partner = agent.partner_id
        agent.unlink()
        self.assertFalse(partner.exists())

    def test_assistants_are_not_offered_as_mentions(self):
        agent = self._agent('Recruitment screener')
        department = self.env['hr.department'].create({'name': 'Recruiting desk'})
        department.action_create_ai_assistant()
        assistant = department.ai_assistant_user_id
        self.assertTrue(assistant.active)
        colleague = new_test_user(self.env, 'recruiting_colleague', name='Recruiting Colleague',
                                  groups='base.group_user')
        names = self._mentions('Recruit')
        self.assertIn(colleague.name, names, 'People are still suggested')
        self.assertNotIn(assistant.name, names, 'An AI assistant user would never answer a mention')
        self.assertNotIn(agent.name, names, "The agent's chat partner is archived, like OdooBot's")
