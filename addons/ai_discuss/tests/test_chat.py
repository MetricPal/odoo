from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal
from odoo.addons.ai_discuss.controllers.messaging_menu import (
    AiDiscussMessagingMenuController,
)


@tagged('post_install', '-at_install')
class TestAssistantChat(TransactionCase):
    """ADR 0013 phase 2: assistant chats in Discuss."""

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
        cls.person = new_test_user(cls.env, 'chat_person', name='Sara Ahmadi',
                                   groups='base.group_user,ai_agent.group_user')
        cls.outsider = new_test_user(cls.env, 'chat_outsider', groups='base.group_user,ai_agent.group_user')
        hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        Agent = cls.env['ai.agent']
        cls.helper = Agent.create({'name': 'HR policy helper', 'description': 'Leave and onboarding',
                                   'engine_id': cls.engine.id, 'department_id': hr.id,
                                   'user_ids': [Command.set(cls.person.ids)]})
        cls.finance = Agent.create({'name': 'Finance helper', 'engine_id': cls.engine.id,
                                    'user_ids': [Command.set(cls.person.ids)]})
        cls.draft = Agent.create({'name': 'Not ready', 'engine_id': cls.engine.id,
                                  'user_ids': [Command.set(cls.person.ids)]})
        (cls.helper | cls.finance).action_activate()
        cls.finance.action_pause()
        cls.Channel = cls.env['discuss.channel'].with_user(cls.person)

    def _chat(self, agent, user=None):
        return self.env['discuss.channel'].sudo().search(
            [('ai_agent_id', '=', agent.id), ('channel_member_ids.partner_id', '=', (user or self.person).partner_id.id)])

    def _say(self, chat, text, user=None):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            return chat.with_user(user or self.person).message_post(body=text, message_type='comment',
                                                                    subtype_xmlid='mail.mt_comment')

    def _agent_messages(self, chat, agent):
        return chat.sudo().message_ids.filtered(lambda m: m.author_id == agent.partner_id)

    def test_assistants_get_a_chat_once_for_their_audience(self):
        self.person._on_webclient_bootstrap()
        helper_chat, finance_chat = self._chat(self.helper), self._chat(self.finance)
        self.assertTrue(helper_chat and finance_chat, 'Answering and paused assistants are listed')
        self.assertFalse(self._chat(self.draft), 'A draft agent is not offered')
        self.assertEqual(helper_chat.channel_type, 'chat')
        self.assertEqual(helper_chat.channel_member_ids.partner_id, self.person.partner_id | self.helper.partner_id)
        self.assertTrue(helper_chat.channel_member_ids.filtered(
            lambda m: m.partner_id == self.person.partner_id).is_pinned)
        self.outsider._on_webclient_bootstrap()
        self.assertFalse(self._chat(self.helper, self.outsider), 'Only the audience gets a chat')
        self.person._on_webclient_bootstrap()
        self.assertEqual(len(self._chat(self.helper)), 1, 'Made once')
        domain = AiDiscussMessagingMenuController()._get_menu_tab_filter_domain('chat', 'chat_assistant')
        found = self.env['discuss.channel'].with_user(self.person).search(domain)
        self.assertEqual(found & (helper_chat | finance_chat), helper_chat | finance_chat)
        self.assertTrue(all(found.sudo().mapped('ai_agent_id')), 'Only assistant chats (demo assistants aside)')

    def test_a_message_is_a_question_and_the_answer_comes_from_the_assistant(self):
        self.person._on_webclient_bootstrap()
        chat = self._chat(self.helper).with_user(self.person)
        with patch.object(type(self.env['discuss.channel.member']), '_notify_typing') as typing:
            self._say(chat, 'Can I carry over unused annual leave?')
        typing.assert_called_with(True)
        run = self.env['ai.agent.run'].sudo().search([('origin_model', '=', 'discuss.channel'),
                                                       ('origin_res_id', '=', chat.id)])
        self.assertEqual((run.prompt, run.user_id, run.agent_id, run.state),
                         ('Can I carry over unused annual leave?', self.person, self.helper, 'queued'))
        self.assertEqual(chat.sudo().ai_conversation_id, run.conversation_id)
        internal(run).write({'state': 'completed', 'answer': 'Yes, up to 5 days.'})
        run._notify_origin()
        answer = self._agent_messages(chat, self.helper)
        self.assertEqual(len(answer), 1)
        self.assertIn('Yes, up to 5 days.', str(answer.body))
        # A follow-up continues the same conversation; the answer does not ask again.
        self._say(chat, 'And parental leave?')
        runs = self.env['ai.agent.run'].sudo().search([('origin_res_id', '=', chat.id),
                                                        ('origin_model', '=', 'discuss.channel')])
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs.conversation_id, run.conversation_id)
        follow_up = runs - run
        internal(follow_up).write({'state': 'failed', 'error_message': 'Hermes stopped without a completed answer.'})
        follow_up._notify_origin()
        self.assertIn('Hermes stopped', str(self._agent_messages(chat, self.helper)[0].body))

    def test_paused_assistants_and_people_outside_the_audience_get_a_plain_reply(self):
        self.person._on_webclient_bootstrap()
        self._say(self._chat(self.finance), 'Hello?')
        reply = self._agent_messages(self._chat(self.finance), self.finance)
        self.assertEqual(len(reply), 1, 'Says why instead of staying silent')
        self.assertFalse(self.env['ai.agent.run'].sudo().search([('agent_id', '=', self.finance.id)]))
        # Someone outside the audience who opens a chat with the partner by hand gets no answer from the agent.
        outsider_chat = self.env['discuss.channel'].with_user(self.outsider)._get_or_create_chat(
            [self.helper.partner_id.id])
        outsider_chat.sudo().ai_agent_id = self.helper
        self._say(outsider_chat, 'What is my manager earning?', user=self.outsider)
        self.assertFalse(self.env['ai.agent.run'].sudo().search([('user_id', '=', self.outsider.id)]))
        self.assertEqual(len(self._agent_messages(outsider_chat, self.helper)), 1)
