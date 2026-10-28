from datetime import date, timedelta

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.marketing_intel_plan.models.campaign_page import _without_state


@tagged('post_install', '-at_install')
class TestCampaignPage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'mic_user', groups='marketing_intel.group_mi_user')
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        for table in ('mi_brand', 'mi_plan'):
            cls.env.cr.execute(f'UPDATE {table} SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io'})
        email = cls.env['mi.channel'].search([('code', 'in', ('email', 'content'))])
        Plan = cls.env['mi.plan'].with_user(cls.user)
        today = date.today()
        cls.plan = Plan.create({'name': 'Year-End Sale', 'brand_id': cls.brand.id, 'budget': 85000,
                                'date_start': today, 'date_end': today + timedelta(days=61),
                                'channel_ids': [Command.set(email.ids)]})
        cls.done = Plan.create({'name': 'Q3 Refresh', 'brand_id': cls.brand.id, 'budget': 60000,
                                'date_start': today, 'date_end': today + timedelta(days=10)})
        cls.done.sudo().state = 'done'

    def test_smart_buttons(self):
        plan = self.plan
        self.assertEqual(plan.duration_days, 62)
        self.assertIn('→', plan.timeline_label)
        self.assertEqual(plan.channel_count, 2)
        self.assertIn('Email', plan.channel_label)
        self.assertEqual((plan.approval_count, plan.approval_done), (0, 0))
        self.assertEqual(plan.with_user(self.user).action_open_channels()['res_model'], 'mi.plan.item')

    def test_dashboard_counts_ignore_stage_filters(self):
        self.assertEqual(_without_state([('state', '=', 'done'), ('brand_id', '=', 1)]),
                         [(1, '=', 1), ('brand_id', '=', 1)])
        Plan = self.env['mi.plan'].with_user(self.user)
        data = Plan.get_campaign_dashboard([('brand_id', '=', self.brand.id), ('state', '=', 'done')])
        counts = {s['filter']: s['count'] for s in data['stages']}
        self.assertEqual((counts['stage_research'], counts['stage_results']), (1, 1))
        tiles = {t['filter']: t for t in data['tiles']}
        self.assertEqual(tiles['my_activities']['value'], '1', 'the owner has the next-step activity')
        self.assertIn('145,000', tiles['this_quarter']['value'])

    def test_print_and_gear_actions(self):
        html = self.env['ir.actions.report']._render_qweb_html(
            'marketing_intel_plan.action_report_campaign', self.plan.ids)[0]
        self.assertIn(b'Year-End Sale', html)
        names = self.env['ir.actions.server'].search([('binding_model_id.model', '=', 'mi.plan')]).mapped('name')
        self.assertIn('Duplicate & edit', names)
        self.assertIn('Save as template', names)
