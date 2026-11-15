from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal
from odoo.addons.marketing_intel_research.models.research import parse_answer

ANSWER = """SUMMARY: Both shops cut monstera prices this week.
POINTS:
- GreenLeaf sells the 30 cm monstera at RM 59 until 30 Nov [1]
- Plantly shows RM 64 with free delivery [2][3]
SOURCES:
[1] Monstera deliciosa 30 cm | https://greenleaf.example/monstera | read today
[2] Plantly monstera | https://www.plantly.example/m | 8 Nov
[3] Monstera (our product) | our data | today
"""


@tagged('post_install', '-at_install')
class TestResearchDesk(TransactionCase):
    """Research desk, plan M5 (approved boards 12.1 to 12.3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        groups = 'marketing_intel.group_mi_user,ai_agent.group_user'
        cls.junior = new_test_user(cls.env, 'research_junior', groups=groups)
        cls.other = new_test_user(cls.env, 'research_other', groups=groups)
        cls.senior = new_test_user(cls.env, 'research_senior', groups='marketing_intel_team.group_mi_senior')
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Research engine', 'url': 'https://hermes.example.com', 'secret_reference': 'AI_AGENT_SECRET_TEST',
            'management_url': 'https://hermes.example.com', 'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        marketing = cls.env['hr.department'].create({'name': 'Research marketing'})
        marketing.action_create_ai_assistant()
        cls.agent = cls.env['ai.agent'].create({'name': 'Marketing Assistant', 'engine_id': engine.id,
                                               'department_id': marketing.id,
                                               'user_ids': [Command.set([cls.junior.id, cls.other.id])]})
        cls.agent.action_activate()
        cls.brand = cls.env['mi.brand'].create({'name': 'Research brand', 'offering': 'Plants',
                                                'ai_agent_id': cls.agent.id})
        cls.greenleaf = cls.env['mi.competitor'].create({'brand_id': cls.brand.id, 'name': 'GreenLeaf'})
        cls.Research = cls.env['mi.research']

    def _ask(self, question='What prices do our competitors show?', user=None, web=True, **kw):
        Research = self.Research.with_user(user or self.junior)
        with patch.object(type(self.Research), '_web_on', lambda self, agent: web):
            return Research.browse(Research.ask(question, self.brand.id, **kw))

    def _answer(self, research, text=ANSWER, state='completed', error=False):
        ai_run = research.sudo().ai_run_id
        agent_internal(ai_run).write({'state': state, 'answer': text, 'error_message': error})
        ai_run._notify_origin()

    # ------------------------------------------------------------------ the answer's form

    def test_parse_answer(self):
        summary, points, sources = parse_answer(ANSWER)
        self.assertEqual(summary, 'Both shops cut monstera prices this week.')
        self.assertEqual(len(points), 2)
        self.assertTrue(points[1].endswith('[2][3]'))
        self.assertEqual([s['number'] for s in sources], [1, 2, 3])
        self.assertEqual(sources[0]['url'], 'https://greenleaf.example/monstera')
        self.assertEqual(sources[2]['url'], '', '"our data" is not a link')

    def test_parse_answer_keeps_only_web_links(self):
        _summary, _points, sources = parse_answer('SOURCES:\n[1] Bad | javascript:alert(1) | today')
        self.assertEqual(sources[0]['url'], '')

    def test_a_reply_without_the_form_is_the_summary(self):
        summary, points, sources = parse_answer('I could not find prices for this plant.')
        self.assertEqual(summary, 'I could not find prices for this plant.')
        self.assertFalse(points or sources)

    # ------------------------------------------------------------------ asking

    def test_ask_queues_a_question_as_the_person(self):
        research = self._ask()
        self.assertEqual(research.state, 'searching')
        self.assertEqual(research.user_id, self.junior)
        self.assertEqual(research.looked_in, 'Web, our data')
        run = research.sudo().ai_run_id
        self.assertTrue(run)
        self.assertEqual(run.user_id, self.junior, 'the question counts against the person, not the assistant')
        prompt = research._prompt()
        self.assertIn('<<<QUESTION\nWhat prices do our competitors show?\nQUESTION>>>', prompt)
        self.assertIn('Search the public web', prompt)
        self.assertIn('Competitors: GreenLeaf', prompt)

    def test_without_web_search_only_our_data(self):
        research = self._ask(web=False)
        self.assertFalse(research.use_web)
        self.assertEqual(research.looked_in, 'our data')
        self.assertIn('Do not search the web.', research._prompt())
        with self.assertRaises(UserError):
            self._ask(web=False, use_data=False)

    def test_the_question_is_checked(self):
        with self.assertRaises(UserError):
            self._ask('   ')
        with self.assertRaises(UserError):
            self._ask('x' * 1001)

    def test_no_assistant(self):
        with patch.object(type(self.env['mi.panel']), '_mi_assistant_agents',
                          lambda self: self.env['ai.agent']):
            self.assertFalse(self.Research.with_user(self.junior).get_desk()['assistant'])
            with self.assertRaises(UserError):
                self._ask()

    def test_desk(self):
        with patch.object(type(self.Research), '_web_on', lambda self, agent: False):
            desk = self.Research.with_user(self.junior).get_desk()
        self.assertTrue(desk['assistant'])
        self.assertFalse(desk['web'])
        self.assertFalse(desk['ai_manager'])
        self.assertFalse(desk['profile_id'], 'only AI Agent managers get the profile')
        self.assertIn(self.brand.id, [b['id'] for b in desk['brands']])

    # ------------------------------------------------------------------ the answer

    def test_answered(self):
        research = self._ask()
        self._answer(research)
        self.assertEqual(research.state, 'answered')
        self.assertEqual(research.summary, 'Both shops cut monstera prices this week.')
        self.assertEqual(len(research.line_ids), 2)
        self.assertEqual(research.source_count, 3)
        self.assertEqual(research.source_ids.sorted('number').mapped('site'),
                         ['greenleaf.example', 'plantly.example', 'our data'])
        self.assertEqual(research.line_ids[0].plain_text, 'GreenLeaf sells the 30 cm monstera at RM 59 until 30 Nov')
        self.assertTrue(research.took_label)

    def test_could_not_answer(self):
        research = self._ask()
        self._answer(research, text='', state='failed', error='The assistant did not reply in time')
        self.assertEqual(research.state, 'failed')
        self.assertTrue(research.error.startswith('The assistant could not answer this question. Please ask'),
                        'a plain reason and who to ask; the technical one stays on the AI request')
        self.assertIn('AI Agent managers', research.error)

    def test_save_ticked_lines_as_market_changes(self):
        research = self._ask()
        self._answer(research)
        with self.assertRaises(UserError):
            research.action_save_findings()
        line = research.line_ids.sorted('sequence')[0]
        line.selected = True
        research.action_save_findings()
        finding = line.finding_id
        self.assertTrue(finding)
        self.assertEqual(finding.kind, 'research')
        self.assertEqual(finding.competitor_id, self.greenleaf, 'a known competitor named in the line is linked')
        self.assertIn('https://greenleaf.example/monstera', finding.summary)
        self.assertEqual(research.saved_label, '1 market change')
        with self.assertRaises(UserError):
            research.action_save_findings()  # nothing new ticked

    def test_turn_into_a_suggested_campaign(self):
        research = self._ask()
        self._answer(research)
        action = research.action_suggest_campaign()
        recommendation = self.env['mi.recommendation'].browse(action['res_id'])
        self.assertEqual(recommendation.origin, 'research')
        self.assertIn('Both shops cut monstera prices', recommendation.problem)
        self.assertEqual(research.saved_label, '1 suggested campaign')

    def test_follow_up(self):
        research = self._ask()
        self._answer(research)
        research.followup_text = 'What do their posts say about the bundle?'
        with patch.object(type(self.Research), '_web_on', lambda self, agent: True):
            action = research.action_ask_followup()
        followup = self.Research.browse(action['res_id'])
        self.assertEqual(followup.parent_id, research)
        self.assertEqual(research.followup_ids, followup)
        self.assertFalse(research.followup_text)
        self.assertIn('Both shops cut monstera prices this week.', followup._prompt())

    # ------------------------------------------------------------------ who sees what

    def test_people_see_their_questions_seniors_all(self):
        research = self._ask()
        self._answer(research)
        self.assertFalse(research.with_user(self.other).is_mine)
        with self.assertRaises(AccessError):
            research.with_user(self.other).read(['question'])
        self.assertEqual(research.with_user(self.senior).question, 'What prices do our competitors show?')
        self.assertFalse(research.with_user(self.senior).is_mine)
        with self.assertRaises((AccessError, UserError)):
            research.with_user(self.senior).action_save_findings()

    # ------------------------------------------------------------------ in the assistant's chat (boards 12.4 to 12.6)

    def _chat(self, user=None):
        user = user or self.junior
        return self.env['discuss.channel'].with_user(user)._ai_chat_for(self.agent.with_user(user))

    def _assistant_messages(self, chat):
        return chat.sudo().message_ids.filtered(lambda m: m.author_id == self.agent.sudo().partner_id)

    def _ask_in_chat(self, chat, question='What prices do our competitors show?', web=True):
        Research = self.Research.with_user(self.junior)
        with patch.object(type(self.Research), '_web_on', lambda self, agent: web):
            return Research.browse(Research.ask_in_chat(chat.id, '<p>%s</p>' % question, self.brand.id, web, True))

    def test_research_is_offered_in_the_marketing_assistant_chat(self):
        chat = self._chat()
        self.assertTrue(chat._mi_research_chat())
        other_agent = self.env['ai.agent'].create({'name': 'Ops helper', 'engine_id': self.agent.engine_id.id,
                                                   'user_ids': [Command.set([self.junior.id])]})
        other_agent.action_activate()
        other_chat = self.env['discuss.channel'].with_user(self.junior)._ai_chat_for(other_agent.with_user(self.junior))
        self.assertFalse(other_chat._mi_research_chat(), 'only the Marketing assistant does research')
        with self.assertRaises(UserError):
            self.Research.with_user(self.junior).ask_in_chat(other_chat.id, 'Prices?', self.brand.id)

    def test_ask_in_chat_saves_the_question_and_says_searching(self):
        chat = self._chat()
        runs_before = self.env['ai.agent.run'].sudo().search_count([('user_id', '=', self.junior.id)])
        research = self._ask_in_chat(chat)
        self.assertEqual(research.state, 'searching')
        self.assertEqual(research.channel_id, chat)
        question = chat.sudo().message_ids.filtered(lambda m: m.author_id == self.junior.partner_id)
        self.assertIn('Research · Research brand · Web, our data', question.body)
        self.assertIn('What prices do our competitors show?', question.body)
        self.assertEqual(self.env['ai.agent.run'].sudo().search_count([('user_id', '=', self.junior.id)]),
                         runs_before + 1, 'asked once, as research, not also as a chat question')
        searching = self._assistant_messages(chat)
        self.assertEqual(searching, research.chat_status_message_id)
        self.assertIn("On it. I'm looking into this now and will reply here.", searching.body)
        self.assertIn('Open the answer', searching.body, 'the button shows progress from any page')

    def test_the_answer_comes_back_in_the_chat(self):
        chat = self._chat()
        research = self._ask_in_chat(chat)
        searching = research.chat_status_message_id
        self._answer(research)
        self.assertFalse(searching.exists(), '"Searching" is replaced by the answer')
        answer = self._assistant_messages(chat)
        self.assertEqual(len(answer), 1)
        # Plain words, as a person replies: no status labels, no [n] markers (owner, 2026-11-13).
        self.assertIn('Both shops cut monstera prices this week.', answer.body)
        self.assertIn('GreenLeaf sells the 30 cm monstera at RM 59 until 30 Nov', answer.body)
        self.assertNotIn('[1]', answer.body)
        self.assertNotIn('Answered', answer.body)
        self.assertIn('I used 3 sources; web pages can be out of date', answer.body)
        self.assertIn('Open the answer', answer.body)
        self.assertIn('/odoo/action-marketing_intel_research.action_research/%s' % research.id, answer.body)

    def test_could_not_answer_in_the_chat(self):
        chat = self._chat()
        research = self._ask_in_chat(chat)
        self._answer(research, text='', state='failed', error='The assistant did not reply in time')
        answer = self._assistant_messages(chat)
        self.assertIn("Sorry, I couldn't find an answer. The assistant could not answer this question.", answer.body)
        self.assertNotIn('try again in a little while', answer.body)
        self.assertNotIn('The assistant did not reply in time', answer.body, 'the reason stays on the answer page')
        self.assertIn('Please ask', research.error)
        self.assertIn('Open the answer', answer.body)

    def test_research_command(self):
        chat = self._chat().with_user(self.junior)
        with patch.object(type(self.Research), '_web_on', lambda self, agent: False):
            chat.execute_command_research(body='/research Why did our email clicks drop?')
        research = self.Research.search([('channel_id', '=', chat.id)])
        self.assertEqual(research.question, 'Why did our email clicks drop?')
        self.assertFalse(research.use_web, 'web search is off for the assistant')
        chat.execute_command_research(body='/research')  # alone: only a hint, nothing asked
        self.assertEqual(self.Research.search_count([('channel_id', '=', chat.id)]), 1)

    def test_a_normal_chat_message_is_not_research(self):
        chat = self._chat().with_user(self.junior)
        chat.message_post(body='Hello', message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertFalse(self.Research.search([('channel_id', '=', chat.id)]))

    def test_ask_a_research_question_opens_the_chat(self):
        # As the list header button calls it (the web client's call_button: method, selected ids).
        from odoo.service.model import call_kw
        action = call_kw(self.Research.with_user(self.junior), 'action_ask_in_chat', [[]], {})
        self.assertEqual(action['tag'], 'mi_research_open_chat')
        self.assertEqual(action['params']['channel_id'], self._chat().id)

    def test_a_stuck_run_says_why_and_a_later_answer_still_arrives(self):
        """The run could not be checked (for example a second server without AI_AGENT_ENDPOINTS): the question
        says why instead of Searching forever; when a manager reconciles the run, the answer still arrives."""
        chat = self._chat()
        research = self._ask_in_chat(chat)
        reason = 'Request blocked or engine unavailable. Reason: this server is not approved.'
        self._answer(research, text='', state='uncertain', error=reason)
        self.assertEqual(research.state, 'failed')
        self.assertIn('Please ask', research.error)
        self.assertNotIn('Hermes', research.error)
        self.assertIn("Sorry, I couldn't find an answer", self._assistant_messages(chat)[-1:].body)
        self._answer(research)  # reconciled: Hermes had answered
        self.assertEqual(research.state, 'answered')
        self.assertFalse(research.error)
        self.assertEqual(len(research.line_ids), 2)
        self.assertIn('Both shops cut monstera prices this week.', self._assistant_messages(chat).sorted('id')[-1].body)
