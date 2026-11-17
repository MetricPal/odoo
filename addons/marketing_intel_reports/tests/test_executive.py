from datetime import date, timedelta

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.marketing_intel_reports.models.executive import bounds, previous


@tagged('post_install', '-at_install')
class TestExecutiveOverview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.brand = cls.env['mi.brand'].create({'name': 'Overview brand'})
        cls.plan = cls.env['mi.plan'].create({
            'name': 'Overview campaign', 'brand_id': cls.brand.id, 'budget': 1000,
            'date_start': cls.today.replace(day=1), 'date_end': cls.today + timedelta(days=20)})
        cls.plan.utm_campaign_id = cls.plan.utm_campaign_id or cls.env['utm.campaign'].create({'name': 'Overview utm'})
        cls.env['mi.plan.spend'].create([
            {'plan_id': cls.plan.id, 'name': 'Ads', 'amount': 300, 'date': cls.today},
            {'plan_id': cls.plan.id, 'name': 'Print', 'amount': 200, 'date': cls.today}])
        cls.crm = 'crm.lead' in cls.env
        if cls.crm:
            Lead = cls.env['crm.lead']
            leads = Lead.create([{'name': 'L%s' % i, 'type': 'opportunity', 'campaign_id': cls.plan.utm_campaign_id.id,
                                  'expected_revenue': 100 * (i + 1)} for i in range(4)])
            leads[0].action_set_won()

    def test_periods(self):
        start, end = bounds('quarter', date(2026, 11, 17))
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertEqual(previous('quarter', start), (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(bounds('month', date(2026, 2, 10)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(bounds('year', date(2026, 5, 5)), (date(2026, 1, 1), date(2026, 12, 31)))

    def test_numbers_of_the_month(self):
        data = self.env['mi.report.executive'].get_overview('month', brand_id=self.brand.id)
        self.assertFalse(data['denied'])
        self.assertFalse(data['empty'])
        kpis = {k['key']: k for k in data['kpis']}
        self.assertIn('500', kpis['spend']['value'])
        self.assertIn('1,000', kpis['spend']['sub'])  # the budget
        if self.crm:
            self.assertEqual(kpis['leads']['value'], '4')
            self.assertEqual(kpis['won']['value'], '1')
            self.assertIn('100', kpis['revenue']['value'])
            self.assertEqual(kpis['per_spend']['value'], '0.20×')
            self.assertIn('125', kpis['cpl']['value'])
            rows = data['funnel']['rows']
            self.assertEqual([r['count'] for r in rows[:2]], [4, 4])
            self.assertEqual(rows[-1]['count'], 1)
            self.assertEqual(data['funnel']['leads_to_won'], 25.0)

    def test_a_period_that_is_not_over_has_no_comparison(self):
        data = self.env['mi.report.executive'].get_overview('month', brand_id=self.brand.id, compare=True)
        self.assertTrue(data['part'])
        self.assertFalse(data['compare'])
        self.assertTrue(any('not over' in note for note in data['notes']))
        self.assertTrue(all(not k['change'] for k in data['kpis']))

    def test_trend_has_a_bucket_for_each_week_or_month(self):
        month = self.env['mi.report.executive'].get_overview('month', brand_id=self.brand.id)['trend']
        self.assertTrue(month['weekly'])
        self.assertEqual(sum(month['spend']), 500)
        quarter = self.env['mi.report.executive'].get_overview('quarter', brand_id=self.brand.id)['trend']
        self.assertEqual(len(quarter['labels']), 3)
        year = self.env['mi.report.executive'].get_overview('year', brand_id=self.brand.id)['trend']
        self.assertEqual(len(year['labels']), 12)

    def test_empty_period_and_unknown_period(self):
        other = self.env['mi.brand'].create({'name': 'Quiet brand'})
        data = self.env['mi.report.executive'].get_overview('year', brand_id=other.id)
        self.assertTrue(data['empty'])
        self.assertEqual(data['period'], 'year')
        self.assertEqual(self.env['mi.report.executive'].get_overview('week')['period'], 'quarter')

    def test_attention_lists_a_campaign_over_its_budget(self):
        self.plan.write({'state': 'live'})
        self.env['mi.plan.spend'].create({'plan_id': self.plan.id, 'name': 'More', 'amount': 800, 'date': self.today})
        rows = self.env['mi.report.executive'].get_overview('month', brand_id=self.brand.id)['attention']
        self.assertEqual([r['name'] for r in rows], ['Overview campaign'])
        self.assertEqual(rows[0]['health'], 'off_track')
        self.assertIn('budget', rows[0]['why'])
