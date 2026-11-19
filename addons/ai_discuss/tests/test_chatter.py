from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.agent import SAFE_MODELS
from odoo.addons.ai_agent.models.common import internal


@tagged('post_install', '-at_install')
class TestChatterAssistants(TransactionCase):
    """ADR 0013 phases 3 and 4: ask an assistant from a record's chatter (approved board 11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.person = new_test_user(cls.env, 'chatter_person', name='Sara Ahmadi',
                                   groups='base.group_user,ai_agent.group_user,base.group_partner_manager')
        cls.outsider = new_test_user(cls.env, 'chatter_outsider', groups='base.group_user,ai_agent.group_user')
        Agent = cls.env['ai.agent']
        cls.sales = Agent.create({'name': 'Customer helper', 'description': 'Customers and their history',
                                  'engine_id': cls.engine.id, 'user_ids': [Command.set(cls.person.ids)],
                                  'access_ids': [Command.create({'model_name': 'res.partner', 'field_names': 'name'})]})
        cls.other = Agent.create({'name': 'Leave helper', 'engine_id': cls.engine.id,
                                  'user_ids': [Command.set(cls.person.ids)]})
        cls.paused = Agent.create({'name': 'Paused customer helper', 'engine_id': cls.engine.id,
                                   'user_ids': [Command.set(cls.person.ids)],
                                   'access_ids': [Command.create({'model_name': 'res.partner', 'field_names': 'name'})]})
        (cls.sales | cls.other | cls.paused).action_activate()
        cls.paused.action_pause()
        cls.customer = cls.env['res.partner'].create({'name': 'Hannah Glover'})
        cls.Question = cls.env['ai.chatter.question'].with_user(cls.person)

    def _ask(self, question='How long has she been a customer?', agent=None, user=None):
        Question = self.env['ai.chatter.question'].with_user(user or self.person)
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            return Question.chatter_ask('res.partner', self.customer.id, (agent or self.sales).id, question)

    def test_only_answering_assistants_that_read_this_kind_of_record(self):
        offer = self.Question.chatter_assistants('res.partner')
        mine = (self.sales | self.other | self.paused).ids
        ours = [agent for agent in offer['agents'] if agent['id'] in mine]  # demo assistants aside
        self.assertEqual([agent['name'] for agent in ours], ['Customer helper'],
                         'Not the one without contacts in its data access, not the paused one')
        self.assertEqual(ours[0]['description'], 'Customers and their history')
        self.assertEqual(offer['record_label'], 'contact')
        self.assertEqual(self.Question.chatter_assistants('res.country')['agents'], [], 'No button there')
        self.assertEqual(self.Question.chatter_assistants('not.a.model')['agents'], [])
        outsider = self.env['ai.chatter.question'].with_user(self.outsider)
        self.assertFalse([agent for agent in outsider.chatter_assistants('res.partner')['agents'] if agent['id'] in mine],
                         'Only for its audience')
        with self.assertRaises(AccessError):
            self._ask(user=self.outsider)
        with self.assertRaises(AccessError):
            self._ask(agent=self.other)

    def test_question_and_answer_are_internal_notes(self):
        self._ask()
        asked = self.env['ai.chatter.question'].sudo().search([('res_id', '=', self.customer.id)])
        run = asked.run_id
        self.assertEqual((run.user_id, run.agent_id, run.caller, run.origin_model),
                         (self.person, self.sales, 'chat', 'ai.chatter.question'))
        self.assertIn('Hannah Glover', run.prompt)
        self.assertIn('How long has she been a customer?', run.prompt)
        note = self.customer.message_ids[0]
        self.assertEqual((note.author_id, note.subtype_id), (self.person.partner_id, self.env.ref('mail.mt_note')))
        self.assertIn('Asked Customer helper', str(note.body))
        internal(run).write({'state': 'completed', 'answer': 'Since 2021, three orders.'})
        run._notify_origin()
        answer = self.customer.message_ids[0]
        self.assertEqual((answer.author_id, answer.subtype_id, answer.message_type),
                         (self.sales.partner_id, self.env.ref('mail.mt_note'), 'comment'))
        self.assertIn('Since 2021, three orders.', str(answer.body))
        self.assertIn('On behalf of Sara Ahmadi', str(answer.body))
        self.assertFalse(self.env['mail.mail'].sudo().search([('mail_message_id', 'in', (note | answer).ids)]),
                         'Nothing is emailed')

    def test_no_answer_says_why(self):
        self._ask()
        run = self.env['ai.chatter.question'].sudo().search([('res_id', '=', self.customer.id)]).run_id
        internal(run).write({'state': 'failed', 'error_message': 'Hermes stopped without a completed answer.'})
        run._notify_origin()
        self.assertIn('could not answer', str(self.customer.message_ids[0].body))

    def test_questions_are_checked(self):
        with self.assertRaisesRegex(UserError, 'Write your question'):
            self._ask('   ')
        with self.assertRaisesRegex(UserError, 'at most'):
            self._ask('x' * 4001)
        self._ask()
        theirs = self.env['ai.chatter.question'].with_user(self.outsider).search([])
        self.assertFalse(theirs, "Nobody sees another person's questions")

    def test_recruitment_records_can_be_in_data_access(self):
        self.assertTrue({'hr.applicant', 'hr.job'} <= SAFE_MODELS)
        choices = dict(self.env['ai.agent.access']._fields['model_name']._description_selection(self.env))
        for model in ('hr.applicant', 'hr.job'):
            self.assertEqual(model in choices, model in self.env, 'Offered only with the Recruitment app')
