from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.marketing_intel_assistant.models.assistant import _date


@tagged('post_install', '-at_install')
class TestAssistant(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        groups = 'marketing_intel.group_mi_user'
        if cls.env.ref('mass_mailing.group_mass_mailing_user', raise_if_not_found=False):
            groups += ',mass_mailing.group_mass_mailing_user'
        cls.marketer = new_test_user(cls.env, 'mia_marketer', groups=groups)
        cls.other = new_test_user(cls.env, 'mia_other', groups=groups)
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        for table in ('mi_flow', 'mi_plan'):
            cls.env.cr.execute(f'UPDATE {table} SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io'})
        cls.email = cls.env['mi.channel'].search([('code', '=', 'email')])
        start = date.today() + timedelta(days=5)
        cls.plan = cls.env['mi.plan'].with_user(cls.marketer).create({
            'name': 'Clinic open day', 'brand_id': cls.brand.id, 'date_start': start,
            'date_end': start + timedelta(days=10), 'channel_ids': [Command.set(cls.email.ids)]})
        cls.Ask = cls.env['mi.assistant.request'].with_user(cls.marketer).with_context(mi_assistant_no_ai=True)

    def ask(self, text):
        with patch.object(type(self.env['mi.assistant.request']), '_agent', lambda self: False):
            return self.Ask.create({'instruction': text})

    def test_dates(self):
        today = date(2026, 10, 25)
        self.assertEqual(_date('20 Nov', today), date(2026, 11, 20))
        self.assertEqual(_date('Nov 20', today), date(2026, 11, 20))
        self.assertEqual(_date('2027-01-05', today), date(2027, 1, 5))
        self.assertEqual(_date('5 Jan', today), date(2027, 1, 5))
        self.assertIsNone(_date('someday', today))

    def test_create_is_proposed_then_done_and_still_needs_review(self):
        request = self.ask('create campaign "Black Friday" for metric.io with email and social from 20 Nov to 30 Nov, '
                           'budget 500, let the AI write it')
        self.assertEqual(request.state, 'proposed', request.result)
        self.assertEqual(request.understood_by, 'rules')
        self.assertEqual(request.intent['channels'], ['email', 'social'])
        self.assertEqual(request.intent['budget'], 500)
        self.assertTrue(request.intent['ai_writes'])
        self.assertIn('Black Friday', request.proposal)
        self.assertFalse(self.env['mi.plan'].search([('name', '=', 'Black Friday')]), 'nothing before Do it')
        with self.assertRaises(AccessError):
            request.with_user(self.other).action_do()
        with patch.object(type(self.env['mi.plan']), '_ai_start', lambda self: None, create=True):
            request.action_do()
        plan = self.env['mi.plan'].search([('name', '=', 'Black Friday')])
        self.assertEqual(request.state, 'done', request.result)
        self.assertEqual((plan.brand_id, plan.budget, plan.worker), (self.brand, 500, 'ai'))
        self.assertEqual(plan.date_end.month, 11)
        self.assertIn(plan.state, ('brief', 'content'), 'created campaigns still go through review')

    def test_change_report_duplicate_and_review(self):
        request = self.ask('how is the open day campaign doing?')
        self.assertEqual(request.state, 'done', request.result)
        self.assertIn('Clinic open day', request.result)
        self.assertIn('Next step', request.result)
        overview = self.ask('report all')
        self.assertIn('active campaign', overview.result)

        copy = self.ask('duplicate Clinic open day starting 1 Dec')
        self.assertEqual(copy.state, 'proposed', copy.result)
        copy.action_do()
        duplicate = self.env['mi.plan'].browse(copy.res_id)
        self.assertEqual((duplicate.date_start.month, duplicate.date_start.day), (12, 1))

        unknown = self.ask('cancel campaign Nonexistent thing')
        self.assertEqual(unknown.state, 'failed')
        self.assertIn('no campaign', unknown.result)
        ambiguous = self.ask('send open day for review')  # the campaign and its copy both match
        self.assertEqual(ambiguous.state, 'failed')
        self.assertIn('Several', ambiguous.result)

        review = self.ask('send "Clinic open day (copy)" for review')
        self.assertEqual(review.state, 'proposed', review.result)
        review.action_do()  # no approver configured or drafts not ready: the usual review rules apply
        self.assertIn(review.state, ('done', 'failed'))
        if review.state == 'failed':
            self.assertIn('review', review.result.lower())

    def test_ai_answer_is_validated(self):
        with patch.object(type(self.env['mi.assistant.request']), '_agent', lambda self: False):
            request = self.Ask.create({'instruction': 'make it pop for the holidays please'})
        self.assertEqual(request.state, 'failed')
        self.assertIn('did not understand', request.result)
        # simulate the agent path: a run answers with JSON
        request.sudo().write({'state': 'thinking'})
        request._apply_answer('```json\n{"action": "change_campaign", "campaign": "Clinic open day", '
                              '"budget": 750, "channels": ["email", "sms", "fax"]}\n```')
        self.assertEqual(request.state, 'proposed', request.result)
        self.assertEqual(request.intent['channels'], ['email', 'sms'])
        request.action_do()
        self.assertEqual(self.plan.budget, 750)
        self.assertEqual(sorted(self.plan.channel_ids.mapped('code')), ['email', 'sms'])
        bad = self.ask('make it pop')
        bad.sudo().write({'state': 'thinking'})
        bad._apply_answer('{"action": "delete_everything"}')
        self.assertEqual(bad.state, 'failed')
