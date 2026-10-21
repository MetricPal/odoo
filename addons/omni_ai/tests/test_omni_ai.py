from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal
from odoo.addons.omni_channel.tests import test_inbox


@tagged('post_install', '-at_install')
class TestOmniAiReply(test_inbox.TestOmniInbox):
    """Reuses the inbox fixture; only the tests below run here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.operator.write({'group_ids': [Command.link(cls.env.ref('ai_agent.group_user').id)]})
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Reply engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Reply drafter', 'engine_id': engine.id,
                                               'user_ids': [Command.set(cls.operator.ids)]})
        cls.agent.action_activate()

    def _reply_draft(self):
        self._receive()
        conversation = self._process().with_user(self.operator)
        conversation.action_assign_me()
        self._draft()
        action = conversation.action_prepare_reply()
        return self.env['omni.command'].browse(action['res_id']).with_user(self.operator)

    def _finish(self, command, answer):
        run = command.ai_run_id.sudo()
        agent_internal(run).write({'state': 'completed', 'answer': answer})
        run._notify_origin()

    def test_ai_reply_fills_the_empty_draft_and_still_needs_approval(self):
        command = self._reply_draft()
        command.action_ai_draft_reply()
        run = command.ai_run_id.sudo()
        self.assertIn('Please help with my order.', run.prompt)
        self.assertIn('untrusted text from the customer', run.prompt)
        self.assertTrue(command.ai_drafting)
        self._finish(command, 'Thanks for writing. A colleague will check your order today.')
        self.assertEqual(command.body, 'Thanks for writing. A colleague will check your order today.')
        self.assertEqual(command.state, 'draft', 'Nothing is submitted or sent by the agent')
        self.assertFalse(command.approval_request_id)

    def test_ai_reply_never_overwrites_text_a_person_wrote(self):
        command = self._reply_draft()
        command.write({'body': 'My own words.'})
        command.action_ai_draft_reply()
        self._finish(command, 'Suggested words.')
        self.assertEqual(command.body, 'My own words.')
        self.assertEqual(command.ai_suggestion, 'Suggested words.')
        command.action_ai_use_suggestion()
        self.assertEqual(command.body, 'Suggested words.')

    def test_only_draft_replies_with_a_conversation_can_be_drafted(self):
        command = self._reply_draft()
        command.write({'body': 'Ready.'})
        command.action_submit()
        with self.assertRaises(UserError):
            command._ai_ask(self.agent)


# Run only this class's own tests, not the inherited inbox suite again.
for _name in dir(test_inbox.TestOmniInbox):
    if _name.startswith('test_') and _name not in vars(TestOmniAiReply):
        setattr(TestOmniAiReply, _name, None)
