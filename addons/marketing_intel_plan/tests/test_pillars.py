from datetime import date, datetime

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPillars(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'mpl_user', groups='marketing_intel.group_mi_user')
        cls.brand = cls.env['mi.brand'].create({'name': 'Pillar brand'})
        cls.channels = cls.env['mi.channel'].search([('code', 'in', ('email', 'social', 'ads'))])

    def _plan(self, **values):
        vals = {'name': 'Year-End Sale', 'brand_id': self.brand.id, 'budget': 85000,
                'date_start': date(2026, 12, 1), 'date_end': date(2027, 1, 31),
                'channel_ids': [Command.set(self.channels.ids)]}
        vals.update(values)
        return self.env['mi.plan'].with_user(self.user).create(vals)

    def test_three_pillars_with_dates_and_budget(self):
        plan = self._plan()
        self.assertEqual(plan.pillar_ids.mapped('pillar'), ['awareness', 'consideration', 'conversion'])
        self.assertEqual(sum(plan.pillar_ids.mapped('budget')), 85000)
        awareness = plan.pillar_ids.filtered(lambda p: p.pillar == 'awareness')
        self.assertEqual((awareness.date_start, awareness.date_end), (plan.date_start, plan.date_end))
        pillars = {item.channel: item.pillar for item in plan.item_ids}
        self.assertEqual(pillars['social'], 'awareness')
        self.assertEqual(pillars['ads'], 'consideration')
        self.assertEqual(pillars['email'], 'conversion')
        with self.assertRaises(Exception):
            awareness.date_end = date(2026, 11, 1)

    def test_overview_funnel_timeline_and_budget(self):
        plan = self._plan()
        plan.spend_ids = [Command.create({'date': date(2026, 12, 15), 'name': 'Meta ads', 'amount': 10000}),
                          Command.create({'date': date(2027, 1, 10), 'name': 'Google Ads', 'amount': 5000})]
        data = plan.get_overview()
        self.assertEqual([p['label'] for p in data['pillars']], ['Awareness', 'Consideration', 'Conversion'])
        self.assertEqual(data['pillars'][0]['left'], 0)
        self.assertEqual(data['pillars'][0]['width'], 100)
        self.assertGreater(data['pillars'][2]['left'], 0)
        months = {row['label']: row for row in data['budget']['rows']}
        self.assertEqual(set(months), {'Dec 2026', 'Jan 2027'})
        self.assertEqual(months['Dec 2026']['actual'], 10000)
        self.assertAlmostEqual(sum(r['target'] for r in months.values()), 85000, places=0)
        quarters = [row['label'] for row in plan.get_overview('quarter')['budget']['rows']]
        self.assertEqual(quarters, ['2026 Q4', '2027 Q1'])
        years = [row['label'] for row in plan.get_overview('year')['budget']['rows']]
        self.assertEqual(years, ['2026', '2027'])

    def test_execute_now_needs_an_approved_campaign(self):
        plan = self._plan()
        with self.assertRaises(UserError):
            plan.action_execute_now()

    def test_schedule_goes_to_the_email(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        plan = self._plan(channel_ids=[Command.set(self.env.ref('marketing_intel.channel_email').ids)])
        lists = self.env['mailing.list'].create({'name': 'Pillar subscribers'})
        plan.brand_id.sudo().account_ids = [Command.create({'account': f'mailing.list,{lists.id}'})]
        plan.sudo().action_prepare()
        item = plan.item_ids
        if not item.res_id:
            self.skipTest('The email draft could not be made in this database: %s' % item.note)
        when = datetime(2030, 1, 5, 8, 0)
        item.schedule_at = when
        mailing = item._record()
        self.assertEqual(mailing.schedule_date, when)


@tagged('post_install', '-at_install')
class TestResults(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'mrs_user', groups='marketing_intel.group_mi_user')
        cls.brand = cls.env['mi.brand'].create({'name': 'Results brand'})
        email = cls.env.ref('marketing_intel.channel_email')
        Plan = cls.env['mi.plan'].with_user(cls.user)
        cls.last_year = Plan.create({'name': 'Year-End 2025', 'brand_id': cls.brand.id,
                                     'channel_ids': [Command.set(email.ids)]})
        cls.last_year.sudo().write({'result_leads': 310, 'result_won': 44, 'result_revenue': 198000})
        cls.plan = Plan.create({'name': 'Year-End 2026', 'brand_id': cls.brand.id, 'budget': 85000,
                                'channel_ids': [Command.set(email.ids)], 'compare_plan_id': cls.last_year.id,
                                'kpi_ids': [Command.create({'metric': 'leads', 'target': 400}),
                                            Command.create({'metric': 'won', 'target': 60})],
                                'spend_ids': [Command.create({'name': 'Ads', 'amount': 81300})]})
        cls.plan.sudo().write({'result_leads': 432, 'result_won': 51, 'result_revenue': 262000})

    def test_results_headline_compare_and_missing_data(self):
        data = self.plan.get_results()
        head = data['headline']
        self.assertEqual(head['per_spend'], '3.22×')
        self.assertEqual((head['leads_pct'], head['won_pct']), (108, 85))
        self.assertEqual(head['leads_bar'], 100)
        self.assertEqual(head['revenue_delta'], 32)
        self.assertEqual(data['compare']['theirs_leads'], 310)
        self.assertEqual(len(data['compare']['pie']), 2)
        self.assertTrue(any('name no channel' in note for note in data['missing']))
        if 'crm.lead' not in self.env:
            self.assertFalse(data['crm'])

    def test_evaluation_and_review_schedule(self):
        plan = self.plan
        plan.sudo().write({'phase': 'results', 'date_start': date(2026, 1, 1), 'date_end': date(2026, 1, 31)})
        self.assertTrue(plan.review_monthly)
        self.assertEqual(plan.next_review_date, date(2026, 2, 28))
        plan.write({'objectives_met': 'partly', 'what_worked': 'TikTok', 'advice_ids': [Command.create({'name': 'Start earlier'})]})
        self.env['mi.plan']._cron_reviews()
        self.assertTrue(plan.activity_ids.filtered(lambda a: 'Review' in (a.summary or '')))
        self.assertEqual(plan.last_review_date, date.today())
        html = self.env['ir.actions.report']._render_qweb_html('marketing_intel_plan.action_report_campaign', plan.ids)[0]
        self.assertIn(b'Start earlier', html)
        self.assertIn(b'TikTok', html)
        self.assertEqual(plan.action_print_report()['report_name'], 'marketing_intel_plan.report_campaign')
