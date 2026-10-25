from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

APP_GROUPS = ['omni_channel.group_omni_user', 'messaging_marketing.group_mm_user',
              'mass_mailing.group_mass_mailing_user', 'event.group_event_user']


@tagged('post_install', '-at_install')
class TestCampaignPlan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = ['marketing_intel.group_mi_user'] + [g for g in APP_GROUPS if cls.env.ref(g, raise_if_not_found=False)]
        cls.user = new_test_user(cls.env, 'mip_user', groups=','.join(groups))
        cls.plain = new_test_user(cls.env, 'mip_plain', groups='marketing_intel.group_mi_user')
        for xmlid in ('omni_channel.purpose_marketing', 'omni_channel.purpose_social_media'):
            team = cls.env.ref(xmlid, raise_if_not_found=False)
            if team:
                team.user_ids = [Command.link(cls.user.id), Command.link(cls.plain.id)]
        # Start as a one-brand company: drafts may use the apps' defaults.
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io'})
        codes = ['social', 'messaging', 'email', 'sms', 'event_virtual', 'content']
        cls.channels = cls.env['mi.channel'].search([('code', 'in', codes)])
        cls.option = cls.env['mi.recommendation'].with_user(cls.user).create({
            'brand_id': cls.brand.id, 'name': 'Clinic webinar', 'problem': 'Rival competes on price.',
            'expected_result': '10 demos booked.', 'kpis': '40 sign-ups\n10 demos', 'budget': 500,
            'duration_days': 21, 'channel_ids': [Command.set(cls.channels.ids)]})

    def test_option_must_be_chosen_first(self):
        with self.assertRaises(UserError):
            self.option.with_user(self.user).action_create_plan()

    def test_plan_creates_linked_drafts_in_each_installed_app(self):
        option = self.option.with_user(self.user)
        option.action_choose()
        option.action_create_plan()
        plan = option.plan_ids
        self.assertEqual(len(plan.item_ids), 6)
        self.assertEqual((plan.date_end - plan.date_start).days, 20)
        plan.action_prepare()
        self.assertEqual(plan.state, 'prepared')
        self.assertTrue(plan.utm_campaign_id)
        items = {item.channel: item for item in plan.item_ids}
        expected = {'social': 'omni.social.campaign', 'messaging': 'mm.mailing', 'email': 'mailing.mailing',
                    'sms': 'mailing.mailing', 'event_virtual': 'event.event'}
        for channel, model in expected.items():
            item = items[channel]
            if model not in self.env:
                self.assertEqual(item.draft_status, 'App not installed')
                continue
            self.assertEqual(item.res_model, model, f'{channel}: {item.note}')
            record = item._record()
            self.assertTrue(record, channel)
            self.assertIn(record._fields.get('state') and record.state or 'draft', ('draft', False), channel)
        if 'mailing.mailing' in self.env:
            email = items['email']._record()
            self.assertEqual(email.campaign_id, plan.utm_campaign_id)
            self.assertIn('Rival competes on price.', str(email.body_html))
            self.assertLessEqual(len(items['sms']._record().body_plaintext), 160)
        if 'mm.mailing' in self.env:
            self.assertEqual(items['messaging']._record().utm_campaign_id, plan.utm_campaign_id)
        self.assertTrue(plan.activity_ids, 'channels without an app become to-dos')
        self.assertFalse(items['content'].res_id)
        # Preparing again creates nothing twice.
        before = {c: i.res_id for c, i in items.items()}
        plan.action_prepare()
        self.assertEqual({i.channel: i.res_id for i in plan.item_ids}, before)

    def test_missing_app_rights_leave_a_note_not_an_error(self):
        option = self.option.with_user(self.plain)
        option.action_choose()
        option.action_create_plan()
        plan = option.plan_ids
        plan.action_prepare()
        self.assertEqual(plan.state, 'prepared')
        for item in plan.item_ids.filtered(lambda i: i.channel in ('email', 'event_virtual') and i.available):
            self.assertFalse(item.res_id)
            self.assertTrue(item.note)

    def test_calendar_clash_warning(self):
        option = self.option.with_user(self.user)
        option.action_choose()
        first = self.env['mi.plan'].with_user(self.user)._from_recommendation(option)
        second = self.env['mi.plan'].with_user(self.user)._from_recommendation(option)
        self.assertIn(first.name, second.clash_note)
        first.action_cancel()
        second.invalidate_recordset(['clash_note'])
        self.assertFalse(second.clash_note)

    def test_results_targets_and_learning_feed_the_next_analysis(self):
        option = self.option.with_user(self.user)
        option.action_choose()
        option.action_create_plan()
        plan = option.plan_ids
        plan.action_prepare()
        plan.write({'kpi_ids': [Command.create({'metric': 'leads', 'target': 4}),
                                Command.create({'metric': 'clicks', 'target': 10})],
                    'learning_note': 'Webinar invites worked best on Tuesday mornings.'})
        campaign = plan.utm_campaign_id
        if 'crm.lead' in self.env:
            Lead = self.env['crm.lead'].sudo()
            Lead.create([{'name': f'Lead {i}', 'campaign_id': campaign.id, 'type': 'opportunity'} for i in range(2)])
            won = Lead.create({'name': 'Won', 'campaign_id': campaign.id, 'type': 'opportunity',
                               'expected_revenue': 1500})
            won.action_set_won()
        if 'link.tracker.click' in self.env:
            link = self.env['link.tracker'].sudo().create({'url': 'https://metric.example/webinar',
                                                           'campaign_id': campaign.id})
            self.env['link.tracker.click'].sudo().create([{'link_id': link.id, 'campaign_id': campaign.id,
                                                           'ip': f'10.0.0.{i}'} for i in range(5)])
        plan.action_done()
        self.assertTrue(plan.results_at)
        self.assertEqual(plan.state, 'done')
        leads = plan.kpi_ids.filtered(lambda k: k.metric == 'leads')
        if 'crm.lead' in self.env:
            self.assertEqual(plan.result_leads, 3)
            self.assertEqual(plan.result_won, 1)
            self.assertEqual(plan.result_revenue, 1500)
            self.assertEqual(leads.progress, 75)
            self.assertAlmostEqual(plan.cost_per_lead, 500 / 3, places=2)
        if 'link.tracker.click' in self.env:
            self.assertEqual(plan.result_clicks, 5)
        lines = self.brand.with_user(self.user)._learning_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn('Tuesday mornings', lines[0])
        self.assertIn('Leads: target 4', lines[0])

    def test_campaign_without_suggestion_channels_and_goal(self):
        goal = self.env['mi.goal'].sudo().create({'brand_id': self.brand.id, 'name': 'Leads this quarter',
                                                   'measure': 'leads', 'target': 10})
        social, email = (self.env.ref('marketing_intel.channel_social'), self.env.ref('marketing_intel.channel_email'))
        plan = self.env['mi.plan'].with_user(self.user).with_context(default_brand_id=self.brand.id).create({
            'name': 'Hand-made webinar', 'goal_id': goal.id, 'channel_ids': [Command.set((social | email).ids)]})
        self.assertEqual(plan.brand_id, self.brand)
        self.assertFalse(plan.recommendation_id)
        self.assertEqual(sorted(plan.item_ids.mapped('channel')), ['email', 'social'])
        plan.channel_ids = [Command.unlink(email.id)]
        self.assertEqual(plan.item_ids.mapped('channel'), ['social'])
        plan.sudo().write({'result_leads': 4})
        self.assertEqual(goal.achieved, 4)
        self.assertEqual(goal.progress, 40)
        brand = self.brand.with_user(self.user)
        self.assertEqual(brand.campaign_count, 1)
        self.assertEqual(brand.action_new_campaign()['context']['default_brand_id'], self.brand.id)

    def test_use_this_idea_starts_a_campaign(self):
        option = self.option.with_user(self.user)
        action = option.action_use_idea()
        self.assertEqual(option.state, 'chosen')
        plan = self.env['mi.plan'].browse(action['res_id'])
        self.assertEqual(plan.recommendation_id, self.option)
        self.assertEqual(plan.brand_id, self.brand)
        self.assertEqual(len(plan.item_ids), 6)
        self.assertEqual(self.brand.with_user(self.user).idea_count, 0)

    def test_several_brands_use_only_their_own_accounts(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        client = self.env['mi.brand'].sudo().create({'name': 'Client B', 'email_from': 'news@clientb.example'})
        email = self.env.ref('marketing_intel.channel_email')
        plan = self.env['mi.plan'].with_user(self.user).with_context(default_brand_id=client.id).create({
            'name': 'Client B newsletter', 'channel_ids': [Command.set(email.ids)]})
        plan.action_prepare()
        item = plan.item_ids
        self.assertFalse(item.res_id, 'never another brand\'s list or the default one')
        self.assertIn('Channels & accounts', item.note)
        own = self.env['mailing.list'].sudo().create({'name': 'Client B subscribers'})
        self.env['mailing.list'].sudo().create({'name': 'metric.io subscribers'})
        client.account_ids = [Command.create({'account': f'mailing.list,{own.id}'})]
        self.assertEqual(client.account_ids.kind, 'Email / SMS mailing list')
        plan.action_prepare()
        mailing = item._record()
        self.assertEqual(mailing.contact_list_ids, own)
        self.assertEqual(mailing.email_from, 'news@clientb.example')

    def test_brand_card_attention(self):
        today = fields.Date.today()
        self.brand.write({'monthly_budget': 1000})
        self.env['mi.goal'].sudo().create({
            'brand_id': self.brand.id, 'name': 'Leads', 'target': 100, 'current': 1,
            'date_start': today - timedelta(days=30), 'date_end': today + timedelta(days=30)})
        self.env['mi.plan'].with_user(self.user).create({'brand_id': self.brand.id, 'name': 'Promo',
                                                         'budget': 1200, 'date_start': today})
        brand = self.brand.with_user(self.user)
        self.assertEqual(brand.goals_behind_count, 1)
        self.assertEqual(brand.budget_month, 1200)
        self.assertEqual(brand.budget_month_pct, 120)
