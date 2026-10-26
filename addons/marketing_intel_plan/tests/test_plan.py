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

    def test_next_step_is_an_activity_for_the_owner(self):
        plan = self.env['mi.plan'].with_user(self.user).create({
            'brand_id': self.brand.id, 'name': 'Activity check',
            'channel_ids': [Command.set(self.channels.filtered(lambda c: c.code == 'content').ids)]})
        activity = plan.mi_activity_id
        self.assertTrue(activity)
        self.assertEqual((activity.user_id, activity.res_model, activity.res_id), (self.user, 'mi.plan', plan.id))
        self.assertEqual(activity.summary, plan.next_step)
        data = self.env['mi.panel'].with_user(self.user).get_panel(brand_id=self.brand.id)
        self.assertIn(plan.next_step, [t['title'] for t in data['todos'] if t['res_id'] == plan.id])
        plan.action_cancel()
        self.assertFalse(plan.mi_activity_id.exists(), 'done by itself when nothing is left to do')
        self.assertFalse(self.env['mail.activity'].search([('res_model', '=', 'mi.plan'), ('res_id', '=', plan.id)]))

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
        self.assertEqual(plan.state, 'content')
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
        self.assertEqual(plan.state, 'content')
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

    def _review_setup(self):
        approver = new_test_user(self.env, 'mip_approver',
                                 groups='marketing_intel.group_mi_user,approval_center.group_approval_center_approver')
        policy = self.env.ref('marketing_intel_plan.policy_campaign')
        policy.write({'company_id': self.env.company.id,
                      'approver_ids': [Command.clear(), Command.create({'user_id': approver.id})]})
        if 'mailing.list' in self.env and not self.brand.account_ids:
            lists = self.env['mailing.list'].sudo().create({'name': 'metric.io subscribers'})
            self.brand.account_ids = [Command.create({'account': f'mailing.list,{lists.id}'})]
        channels = self.env['mi.channel'].search([('code', 'in', ('email', 'sms', 'event_virtual'))])
        plan = self.env['mi.plan'].with_user(self.user).create({
            'brand_id': self.brand.id, 'name': 'Autumn webinar', 'message': 'Join our clinic webinar.',
            'channel_ids': [Command.set(channels.ids)]})
        return approver, plan

    def test_one_review_releases_the_campaign(self):
        if 'mailing.mailing' not in self.env or 'event.event' not in self.env:
            self.skipTest('Email Marketing and Events are needed')
        approver, plan = self._review_setup()
        self.assertEqual(plan.status, 'brief')
        self.assertEqual(set(plan.item_ids.mapped('stage')), {'not_started'})
        plan.action_prepare()
        self.assertEqual(plan.state, 'content')
        self.assertEqual(set(plan.item_ids.mapped('stage')), {'draft'})
        self.assertTrue(plan.needs_me, 'the owner writes the content')
        self.assertIn('send the campaign for review', plan.my_todo)
        plan.action_submit_review()
        self.assertEqual(plan.state, 'review')
        self.assertEqual(plan.review_request_id.state, 'submitted')
        self.assertEqual(set(plan.item_ids.mapped('stage')), {'needs_review'})
        self.assertIn(approver.name, plan.waiting_for)
        self.assertIn(approver.name, plan.next_step)
        self.assertFalse(plan.can_review, 'nobody approves their own campaign')
        self.assertFalse(plan.needs_me, 'the owner waits; it is not on their to-do list')
        self.assertEqual(plan.with_user(approver).my_todo, 'Approve or refuse the campaign')
        mine = self.env['mi.plan'].with_user(approver).search([('needs_me', '=', True)])
        self.assertIn(plan, mine)
        as_approver = plan.with_user(approver)
        self.assertTrue(all(as_approver.item_ids.mapped('preview')), 'the approver reads every channel')
        self.assertIn('Join our clinic webinar.', as_approver.item_ids.filtered(lambda i: i.channel == 'sms').preview)
        with self.assertRaisesRegex(UserError, 'Review tab'):
            as_approver.item_ids[0].action_open()
        email = plan.item_ids.filtered(lambda i: i.channel == 'email')._record()
        self.assertEqual(email.state, 'draft', 'nothing goes out before the approval')
        plan.with_user(approver).action_approve_review()
        plan.invalidate_recordset()
        self.assertEqual(plan.review_request_id.state, 'approved')
        self.assertTrue(plan.review_request_id.executed_at, 'the approval released the campaign')
        self.assertEqual(email.state, 'in_queue')
        self.assertTrue(email.schedule_date)
        stages = {i.channel: i.stage for i in plan.item_ids}
        self.assertEqual(stages['email'], 'scheduled')
        self.assertEqual(stages['event_virtual'], 'out', 'the event is published')
        self.assertEqual((plan.state, plan.status), ('live', 'live'))
        self.assertEqual((plan.channels_out, plan.channel_count), (1, 3))
        self.assertIn('Goes out on', plan.item_ids.filtered(lambda i: i.channel == 'email').next_step)
        email.sudo().state = 'done'
        self.env.invalidate_all()
        plan.action_refresh_results()
        email_line = plan.item_ids.filtered(lambda i: i.channel == 'email')
        self.assertEqual(email_line.stage, 'failed', 'sent to nobody is a failure, not a success')
        self.assertIn('nobody', email_line.next_step)
        self.assertIn('Fix 1 channel', plan.next_step)
        notes = ' '.join(plan.message_ids.mapped('body'))
        self.assertIn('Email: Scheduled', notes)
        self.assertIn('Email: Failed', notes)
        plan.sudo().write({'date_start': fields.Date.today() - timedelta(days=10),
                           'date_end': fields.Date.today() - timedelta(days=1)})
        self.env['mi.plan']._cron_refresh_results()
        self.assertEqual(plan.state, 'done', 'closed automatically after the end date')

    def test_refused_review_goes_back_to_content(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        plan.action_submit_review()
        plan.with_user(approver).action_refuse_review()
        self.assertEqual(plan.state, 'content')
        self.assertTrue(plan.activity_ids.filtered(lambda a: a.user_id == self.user))
        plan.action_submit_review()
        self.assertEqual(plan.state, 'review', 'a new review can be asked')
        self.assertEqual(plan.review_request_id.state, 'submitted')

    def test_review_needs_every_channel_ready(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        self.brand.account_ids = [Command.clear()]
        self.env['mi.brand'].sudo().create({'name': 'Second brand'})  # now each brand needs its own lists
        result = plan.action_submit_review()
        self.assertEqual(result['params']['title'], 'Not sent for review yet')
        self.assertIn('mailing lists', result['params']['message'])
        self.assertEqual(plan.state, 'content', 'nothing was submitted')
        self.assertFalse(plan.review_request_id)
        lists = self.env['mailing.list'].sudo().create({'name': 'metric.io subscribers'})
        self.brand.account_ids = [Command.create({'account': f'mailing.list,{lists.id}'})]
        self.assertIs(plan.action_submit_review(), True)
        self.assertEqual(plan.state, 'review')

    def test_draft_without_lists_needs_fixing(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        plan.action_prepare()
        email_line = plan.item_ids.filtered(lambda i: i.channel == 'email')
        email_line._record().sudo().contact_list_ids = [Command.clear()]
        plan.action_submit_review()
        self.assertEqual(email_line.stage, 'blocked')
        self.assertIn('Choose the mailing lists', email_line.next_step)
        self.assertEqual(plan.state, 'content')

    def test_status_stays_in_review_and_flags_sending_outside(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        plan.action_submit_review()
        email = plan.item_ids.filtered(lambda i: i.channel == 'email')._record().sudo()
        email.write({'state': 'sending'})
        self.env.invalidate_all()
        plan._sync_state()
        self.assertEqual((plan.state, plan.status), ('review', 'review'), 'not live before the approval')
        self.assertIn('before the campaign review', plan.item_ids.filtered(lambda i: i.channel == 'email').next_step)

    def test_only_approver_is_the_owner(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        self.env.ref('marketing_intel_plan.policy_campaign').approver_ids = [
            Command.clear(), Command.create({'user_id': self.user.id})]
        plan.action_submit_review()
        self.assertFalse(plan.can_review)
        self.assertIn('Nobody else can approve', plan.my_todo)

    def test_review_without_approvers_explains_where_to_set_them(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        self.env.ref('marketing_intel_plan.policy_campaign').approver_ids = [Command.clear()]
        result = plan.action_submit_review()
        self.assertIn('Marketing campaign', result['params']['message'])
        self.assertNotEqual(plan.state, 'review')

    def test_duplicate_template_and_repeat(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        plan.action_prepare()
        email = plan.item_ids.filtered(lambda i: i.channel == 'email')._record()
        email.sudo().subject = 'Join our autumn webinar'
        # Duplicate & edit keeps channels and texts, with new drafts.
        copy = self.env['mi.plan'].browse(plan.action_duplicate()['res_id'])
        self.assertEqual(copy.state, 'brief')
        self.assertEqual(sorted(copy.item_ids.mapped('channel')), sorted(plan.item_ids.mapped('channel')))
        copy.action_prepare()
        copied = copy.item_ids.filtered(lambda i: i.channel == 'email')._record()
        self.assertNotEqual(copied, email)
        self.assertEqual(copied.subject, 'Join our autumn webinar')
        # Templates never run and do not count as campaigns.
        template = self.env['mi.plan'].browse(plan.action_save_template()['res_id'])
        self.assertTrue(template.is_template)
        plan.invalidate_recordset(['saved_template_id'])
        self.assertEqual(plan.saved_template_id, template)
        email.sudo().subject = 'Autumn webinar, take two'
        again = self.env['mi.plan'].browse(plan.action_save_template()['res_id'])
        self.assertEqual(again, template, 'saving again updates the same template')
        self.assertEqual(self.env['mi.plan'].search_count([('template_source_id', '=', plan.id)]), 1)
        self.assertEqual(template.item_ids.filtered(lambda i: i.channel == 'email').content_subject,
                         'Autumn webinar, take two')
        with self.assertRaises(UserError):
            template.action_save_template()
        with self.assertRaises(UserError):
            template.action_prepare()
        self.assertNotIn(template, self.brand.plan_ids)
        started = self.env['mi.plan'].browse(template.action_use_template()['res_id'])
        self.assertEqual(started.template_id, template)
        self.assertFalse(started.is_template)
        # The family shares one template: the started campaign and copies update it, never add a second one.
        started.invalidate_recordset(['saved_template_id'])
        self.assertEqual(started.saved_template_id, template)
        self.assertEqual(self.env['mi.plan'].browse(started.action_save_template()['res_id']), template)
        copy = self.env['mi.plan'].browse(started.action_duplicate()['res_id'])
        self.assertEqual(self.env['mi.plan'].browse(copy.action_save_template()['res_id']), template)
        self.assertEqual(template.template_source_id, plan, 'the template keeps where it was first saved from')
        self.assertEqual(template.name, plan.name)
        self.assertEqual(self.env['mi.plan'].search_count([('is_template', '=', True), ('name', '=', plan.name),
                                                           ('brand_id', '=', plan.brand_id.id)]), 1)
        template.invalidate_recordset(['template_use_count'])
        self.assertEqual(template.template_use_count, 2, 'the started campaign and its copy')
        # An unrelated campaign with the same name cannot add a second template of that name.
        namesake = self.env['mi.plan'].with_user(plan.user_id).create({
            'name': plan.name, 'brand_id': plan.brand_id.id, 'channel_ids': [Command.set(plan.channel_ids.ids)]})
        with self.assertRaises(UserError):
            namesake.action_save_template()
        # Weekly repeat: the next run is created a few days before it starts and sent for review, once.
        today = fields.Date.today()
        plan.sudo().write({'repeat': 'weekly', 'date_start': today - timedelta(days=5),
                           'date_end': today + timedelta(days=1)})
        self.assertEqual(plan.next_run_date, today + timedelta(days=2))
        self.env['mi.plan']._cron_repeat()
        run = self.env['mi.plan'].search([('series_id', '=', plan.id)])
        self.assertEqual(len(run), 1)
        self.assertEqual(run.date_start, today + timedelta(days=2))
        self.assertEqual(run.state, 'review', 'quick review: the copy is sent for review by itself')
        plan.invalidate_recordset(['next_run_date'])
        self.assertFalse(plan.next_run_date, 'the newest run carries the series on')
        self.assertEqual(run.next_run_date, today + timedelta(days=9))
        self.env['mi.plan']._cron_repeat()
        self.assertEqual(self.env['mi.plan'].search_count([('series_id', '=', plan.id)]), 1)

    def test_control_panel_shows_progress_timeline_and_todos(self):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing not installed')
        approver, plan = self._review_setup()
        plan.write({'repeat': 'monthly'})
        plan.action_submit_review()
        data = self.env['mi.panel'].with_user(self.user).get_panel(brand_id=self.brand.id)
        self.assertEqual({k['key'] for k in data['kpis']},
                         {'sent', 'clicks', 'leads', 'revenue', 'budget', 'goals'})
        self.assertTrue(all(len(k['trend']) == 8 for k in data['kpis'] if k['trend']))
        row = next(r for r in data['campaigns'] if r['id'] == plan.id)
        self.assertEqual(row['status'], 'review')
        self.assertEqual(row['groups']['waiting'], 3)
        self.assertTrue(row['repeat'])
        kinds = {e['kind'] for e in data['timeline']['upcoming'] + data['timeline']['recent']}
        self.assertTrue({'review', 'repeat'} <= kinds, kinds)
        self.assertTrue(any(e['recurring'] for e in data['timeline']['upcoming'] if e['kind'] == 'repeat'))
        mine = self.env['mi.panel'].with_user(approver).get_panel()
        todo = next(t for t in mine['todos'] if t['res_id'] == plan.id)
        self.assertEqual((todo['model'], todo['title']), ('mi.plan', 'Approve or refuse the campaign'),
                         'the approval activity opens the campaign: one review')
        self.assertEqual(len([t for t in mine['todos'] if t['res_id'] == plan.id]), 1, 'one line per campaign')
        # the owner's next step is an Odoo activity, done by itself when the step is done
        self.assertFalse(plan.mi_activity_id, 'the owner only waits during the review')

    def test_menus_open_the_control_panel_and_todos(self):
        self.assertEqual(self.env.ref('marketing_intel.menu_root').action,
                         self.env.ref('marketing_intel_plan.action_control_panel'))
        self.assertFalse(self.env.ref('marketing_intel.menu_reporting', raise_if_not_found=False))
        self.assertEqual(self.env.ref('marketing_intel_plan.menu_goals').parent_id,
                         self.env.ref('marketing_intel_plan.menu_campaigns_root'))
        menus = self.env['ir.ui.menu'].with_user(self.user).load_menus(False)
        self.assertTrue(menus)

    def test_spend_quarter_and_portfolio(self):
        today = fields.Date.today()
        self.brand.sudo().write({'monthly_budget': 1000, 'owner_type': 'client',
                                 'partner_id': self.env['res.partner'].create({'name': 'Client Co'}).id,
                                 'retainer_fee': 500})
        Plan = self.env['mi.plan'].with_user(self.user)
        first = Plan.create({'brand_id': self.brand.id, 'name': 'Open day', 'budget': 600,
                             'date_start': today, 'date_end': today + timedelta(days=10),
                             'channel_ids': [Command.set(self.channels.filtered(lambda c: c.code == 'email').ids)]})
        second = Plan.create({'brand_id': self.brand.id, 'name': 'Follow-up', 'budget': 700,
                              'date_start': today + timedelta(days=3), 'date_end': today + timedelta(days=12),
                              'channel_ids': [Command.set(self.channels.filtered(lambda c: c.code == 'email').ids)]})
        first.spend_ids = [Command.create({'name': 'Ads', 'amount': 650}), Command.create({'name': 'Print', 'amount': 500})]
        self.assertEqual((first.spent, first.budget_left), (1150, -550))
        # Target quarter: from the start date, changeable, filterable as this / next quarter.
        today = fields.Date.context_today(first)
        this_q = '%s-Q%s' % (today.year, (today.month - 1) // 3 + 1)
        first.sudo().date_start = today
        self.assertEqual(first.target_quarter, this_q)
        nxt = today.year * 4 + (today.month - 1) // 3 + 1
        second.sudo().write({'target_quarter': '%s-Q%s' % (nxt // 4, nxt % 4 + 1)})
        Plan = self.env['mi.plan']
        self.assertIn(first, Plan.search([('quarter_when', '=', 'this')]))
        self.assertNotIn(second, Plan.search([('quarter_when', '=', 'this')]))
        self.assertIn(second, Plan.search([('quarter_when', '=', 'next')]))
        data = self.env['mi.panel'].with_user(self.user).get_portfolio('month')
        row = next(r for g in data['groups'] for r in g['rows'] if r['id'] == self.brand.id)
        self.assertEqual((row['budget'], row['planned'], row['spent']), (1000, 1300, 1150))
        self.assertEqual(row['health'], 'off_track')
        self.assertTrue(row['client'])
        self.assertEqual(row['fee'], 500)
        lane = next(l for l in data['timeline']['lanes'] if l['id'] == self.brand.id)
        bars = {b['id']: b for b in lane['bars']}
        self.assertTrue(bars[first.id]['clash'] and bars[second.id]['clash'], 'overlapping email campaigns clash')
        self.assertNotEqual(bars[first.id]['row'], bars[second.id]['row'], 'overlapping bars get their own row')
        quarter = self.env['mi.panel'].with_user(self.user).get_portfolio('quarter')
        self.assertEqual(next(r for g in quarter['groups'] for r in g['rows'] if r['id'] == self.brand.id)['budget'],
                         3000)
