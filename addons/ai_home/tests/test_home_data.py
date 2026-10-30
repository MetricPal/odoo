from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestHomeData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'home_data_user', name='Daniel Tan',
                                 groups='base.group_user,base.group_partner_manager')
        cls.Home = cls.env['ai.home.item'].with_user(cls.user)

    def _data(self, user=None):
        return self.env['ai.home.item'].with_user(user or self.user).get_home_data()

    def _call_back(self, days=1):
        partner = self.env['res.partner'].create({'name': 'Lim Trading'})
        return partner.activity_schedule('mail.mail_activity_data_todo', summary='Call back Lim Trading',
                                         user_id=self.user.id,
                                         date_deadline=fields.Date.today() - timedelta(days=days))

    def _activity(self, days, summary, user=None, creator=None, kind='mail.mail_activity_data_todo'):
        partner = self.env['res.partner'].create({'name': f'Doc for {summary}'})
        values = {'summary': summary, 'user_id': (user or self.user).id,
                  'date_deadline': fields.Date.context_today(partner) + timedelta(days=days)}
        if isinstance(kind, str):
            return partner.with_user(creator or self.user).activity_schedule(kind, **values)
        return partner.with_user(creator or self.user).activity_schedule(activity_type_id=kind.id, **values)

    def _plan(self, user=None):
        return {row['title']: row for row in self._data(user)['plan']}

    def test_old_sections_are_gone(self):
        data = self._data()
        for gone in ('firstName', 'roleLabel', 'summary', 'live', 'day', 'quickActions'):
            self.assertNotIn(gone, data)

    def test_my_plan_puts_activities_in_sections(self):
        self._activity(-3, 'Send contract')
        self._activity(0, 'Call back Lim')
        self._activity(1, 'Prepare demo')
        self._activity(40, 'Year-end review')
        plan = self._plan()
        self.assertEqual([plan[t]['section'] for t in ('Send contract', 'Call back Lim', 'Prepare demo',
                                                         'Year-end review')], ['late', 'today', 'tomorrow', 'later'])
        late = plan['Send contract']
        self.assertIn('3 days late', late['meta'])
        self.assertEqual((late['model'], late['openModel']), ('mail.activity', 'res.partner'))
        self.assertTrue(late['canDone'])
        self.assertTrue(late['app'])
        order = [row['section'] for row in self._data()['plan']]
        self.assertEqual(order, sorted(order, key=['late', 'today', 'tomorrow', 'week', 'later'].index))

    def test_today_ring_counts_done_late_and_due(self):
        self._activity(-1, 'Late one')
        due = self._activity(0, 'Due one')
        self._activity(0, 'Due two')
        today = self._data()['today']
        self.assertEqual((today['done'], today['late'], today['todo'], today['total']), (0, 1, 2, 3))
        self.Home.run_home_action('mail.activity', due.id, 'action_done')
        today = self._data()['today']
        self.assertEqual((today['done'], today['late'], today['todo'], today['total']), (1, 1, 1, 3))

    def test_week_strip_counts_each_day(self):
        self._activity(0, 'A')
        self._activity(2, 'B')
        self._activity(2, 'C')
        self._activity(2, 'D')
        week = self._data()['week']
        self.assertEqual(len(week), 7)
        self.assertTrue(week[0]['isToday'])
        self.assertEqual([day['count'] for day in week][:3], [1, 0, 3])
        self.assertTrue(week[2]['heavy'], '3 items and over 1.5 x the average')
        self.assertFalse(week[0]['heavy'])

    def test_snooze_and_done_from_my_plan(self):
        activity = self._activity(-1, 'Call back Lim Trading')
        self.Home.run_home_action('mail.activity', activity.id, 'action_reschedule_tomorrow')
        self.assertEqual(activity.date_deadline, fields.Date.context_today(activity) + timedelta(days=1))
        self.Home.run_home_action('mail.activity', activity.id, 'action_reschedule_nextweek')
        self.assertEqual(activity.date_deadline.weekday(), 0)
        self.Home.run_home_action('mail.activity', activity.id, 'action_done')
        self.assertFalse(activity.exists().filtered('active'))
        self.assertNotIn('Call back Lim Trading', self._plan())

    def test_decision_activities_go_to_attention_not_plan(self):
        kind = self.env['mail.activity.type'].create({'name': 'Approve budget', 'home_decision': True})
        activity = self._activity(2, 'Approve the Q4 budget', kind=kind)
        self.assertNotIn('Approve the Q4 budget', self._plan())
        data = self._data()
        row = next(item for item in data['attention'] if item['title'] == 'Approve the Q4 budget')
        self.assertEqual((row['category'], row['model'], row['resId']), ('decision', 'mail.activity', activity.id))
        self.assertEqual(row['primary']['method'], 'action_done')
        self.assertIn('decision', [group['key'] for group in data['attentionGroups']])

    def test_plain_activities_are_not_decisions(self):
        self._activity(-1, 'Approve')
        self.assertFalse([item for item in self._data()['attention'] if item['title'] == 'Approve'])
        self.assertIn('Approve', self._plan(), 'an activity named "Approve" is still a task in the plan')

    def test_waiting_on_others_and_nudge(self):
        colleague = new_test_user(self.env, 'home_waiting_colleague', name='Mei Wong',
                                  groups='base.group_user,base.group_partner_manager')
        activity = self._activity(-3, 'Send contract to Tan', user=colleague)
        self._activity(3, 'Not due yet', user=colleague)
        waiting = self._data()['waiting']
        self.assertEqual([row['title'] for row in waiting], ['Mei · Send contract to Tan'])
        self.assertEqual((waiting[0]['tone'], waiting[0]['initials']), ('bad', 'MW'))
        self.assertIn('3 days late', waiting[0]['meta'])
        self.assertFalse(self._data(colleague)['waiting'], 'the assignee has it in their plan, not in waiting')
        self.assertIn('Send contract to Tan', self._plan(colleague))
        self.Home.run_home_action('mail.activity', activity.id, 'home_nudge')
        document = self.env['res.partner'].browse(activity.res_id)
        note = document.message_ids[:1]
        self.assertIn(colleague.partner_id, note.partner_ids)
        self.assertIn('Send contract to Tan', note.body)
        with self.assertRaises(UserError):
            self.env['ai.home.item'].with_user(colleague).run_home_action('mail.activity', activity.id, 'home_nudge')

    def test_own_request_you_can_approve_shows_once(self):
        if 'approval.center.request' not in self.env:
            self.skipTest('Approvals is not installed')
        admin = self.env.ref('base.user_admin')
        policy = self.env['approval.center.policy'].create({
            'name': 'Home duplicate check', 'has_document': 'no', 'company_id': False,
            'approver_ids': [fields.Command.create({'user_id': admin.id})]})
        request = self.env['approval.center.request'].with_user(admin).create({
            'name': 'Laptop for Mei', 'policy_id': policy.id, 'reason': 'Broken screen'})
        request.action_submit()
        attention = self._data(admin)['attention']
        rows = [item for item in attention if item['model'] == 'approval.center.request' and item['resId'] == request.id]
        if request.with_user(admin).can_review:
            self.assertEqual(len(rows), 1, 'requester and approver: one row')
            self.assertEqual(rows[0]['primary']['method'], 'action_approve')
        else:
            self.assertFalse(rows, 'your own request waits on others: it is on the left')
            self.assertIn(f'waiting-request-{request.id}', [row['key'] for row in self._data(admin)['waiting']])
        keys = [item['key'] for item in attention]
        self.assertEqual(len(keys), len(set(keys)), 'keys are unique')

    def test_only_listed_buttons_can_run(self):
        partner = self.env['res.partner'].create({'name': 'Not a button'})
        with self.assertRaises(UserError):
            self.Home.run_home_action('res.partner', partner.id, 'unlink')
        with self.assertRaises(UserError):
            self.Home.run_home_action('mail.activity', 0, 'action_done')

    def test_decision_sources_list_records_and_allow_only_their_buttons(self):
        source = self.env['ai.home.source'].create({
            'name': 'Partners to check', 'model_name': 'res.partner', 'badge': 'PC',
            'domain': "[('name', 'like', 'HomeSource')]", 'primary_label': 'Archive',
            'primary_method': 'action_archive', 'limit': 2})
        Partner = self.env['res.partner']
        listed = Partner.create([{'name': f'HomeSource {i}'} for i in range(3)])
        other = Partner.create({'name': 'Somebody else'})
        data = self._data()
        rows = [item for item in data['attention'] if item['category'] == f'source_{source.id}']
        self.assertEqual(len(rows), 2, 'at most the limit')
        self.assertEqual((rows[0]['badge'], rows[0]['primary']['method']), ('PC', 'action_archive'))
        self.assertTrue(rows[0]['meta'].startswith('Partners to check'))
        group = next(g for g in data['attentionGroups'] if g['key'] == f'source_{source.id}')
        self.assertEqual((group['label'], group['count'], group['shown']), ('Partners to check', 3, 2))
        self.assertEqual(set(group['action']['domain'][0][2]), set(listed.ids), '"Open all" opens every listed row')
        with self.assertRaises(UserError):
            self.Home.run_home_action('res.partner', other.id, 'action_archive')
        self.Home.run_home_action('res.partner', listed[0].id, 'action_archive')
        self.assertFalse(listed[0].active)
        # The group decides who sees a source.
        source.group_xmlid = 'base.group_system'
        self.assertFalse([item for item in self._data()['attention'] if item['category'] == f'source_{source.id}'])
        with self.assertRaises(UserError):
            self.Home.run_home_action('res.partner', listed[1].id, 'action_archive')

    def test_decision_source_buttons_are_limited(self):
        with self.assertRaises(ValidationError):
            self.env['ai.home.source'].create({'name': 'Bad', 'model_name': 'res.partner', 'primary_method': 'unlink'})
        with self.assertRaises(ValidationError):
            self.env['ai.home.source'].create({'name': 'Bad', 'model_name': 'res.partner',
                                               'primary_method': 'action_does_not_exist'})
        with self.assertRaises(ValidationError):
            self.env['ai.home.source'].create({'name': 'Bad', 'model_name': 'res.partner', 'domain': 'not a domain'})
        source = self.env['ai.home.source'].create({'name': 'Not installed', 'model_name': 'no.such.model'})
        self.assertFalse(source._records())

    def test_default_sources_skip_apps_that_are_not_installed(self):
        sources = self.env['ai.home.source'].search([])
        self.assertTrue(self.env.ref('ai_home.source_time_off'))
        for source in sources.filtered(lambda s: s.model_name not in self.env):
            self.assertFalse(source._usable())
        self._data()  # no error for any default source

    def test_recently_opened_lists_records_the_user_touched_newest_first(self):
        Partner = self.env['res.partner'].with_user(self.user)
        first = Partner.create({'name': 'First touched'})
        second = Partner.create({'name': 'Second touched'})
        first.message_post(body='Called the customer', message_type='comment')
        second.message_post(body='Sent the quote', message_type='comment')
        recent = self._data()['recent']
        names = [item['name'] for item in recent]
        self.assertLess(names.index('Second touched'), names.index('First touched'))
        item = next(item for item in recent if item['name'] == 'Second touched')
        self.assertEqual((item['model'], item['resId']), ('res.partner', second.id))
        self.assertTrue(item['occurred'])
        self.assertLessEqual(len(recent), 4)

    def test_recently_opened_hides_records_the_user_can_no_longer_read(self):
        other_company = self.env['res.company'].create({'name': 'Home other company'})
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Moved away'})
        partner.message_post(body='Note', message_type='comment')
        partner.sudo().company_id = other_company
        self.assertNotIn('Moved away', [item['name'] for item in self._data()['recent']])
        self.assertNotIn('Moved away', ' '.join(item['text'] for item in self._data()['feed']))

    def test_what_just_happened_shows_what_others_did(self):
        colleague = new_test_user(self.env, 'home_colleague', name='Mei Wong',
                                  groups='base.group_user,base.group_partner_manager')
        partner = self.env['res.partner'].with_user(colleague).create({'name': 'Tan Holdings'})
        partner.message_subscribe(partner_ids=self.user.partner_id.ids)
        partner.with_user(colleague).message_post(body='Please check the delivery date', message_type='comment',
                                                  partner_ids=self.user.partner_id.ids)
        partner.with_user(self.user).message_post(body='My own note', message_type='comment')
        feed = self._data()['feed']
        entry = next(entry for entry in feed if 'Please check the delivery date' in entry['text'])
        self.assertEqual((entry['actor'], entry['forMe']), ('Mei Wong', True))
        self.assertIn('Tan Holdings', entry['text'])
        self.assertFalse([e for e in feed if 'My own note' in e['text']], 'your own work is in Recent, not here')
        self.assertIn('Tan Holdings', [r['name'] for r in self._data()['recent']])
        self.assertFalse([entry for entry in feed if entry['model'].startswith('ir.')], 'no configuration records')

    def test_without_an_assistant(self):
        data = self._data()
        self.assertEqual(data['agents'], [], 'Users outside AI Agent see no agents')
        self.assertEqual(data['prompts'], [])

    def test_failed_workflow_runs_need_attention_of_administrators(self):
        if 'workflow.run' not in self.env:
            self.skipTest('Workflows is not installed')
        from odoo.addons.workflow_center.models.workflow import internal

        admin = self.env.ref('base.user_admin')
        flow = self.env['workflow.definition'].with_user(admin).create({
            'name': 'Finance sync', 'model_id': self.env['ir.model']._get('res.partner').id,
        })
        Run = internal(self.env['workflow.run'].sudo())
        failed = Run.create({'workflow_id': flow.id, 'record_id': admin.partner_id.id,
                             'name': 'Azure Interior', 'revision': 1, 'state': 'failed'})
        Run.create({'workflow_id': flow.id, 'record_id': admin.partner_id.id,
                    'name': 'Preview', 'revision': 1, 'state': 'failed', 'is_test': True})
        attention = self._data(admin)['attention']
        item = next(item for item in attention if item['resId'] == failed.id and item['model'] == 'workflow.run')
        self.assertEqual(item['title'], 'Finance sync failed on Azure Interior')
        self.assertEqual((item['primary']['method'], item['secondary']['label']), ('action_retry', 'View run'))
        self.assertNotIn('Finance sync failed on Preview', [i['title'] for i in attention], 'previews are not real runs')
        self.assertFalse([i for i in self._data()['attention'] if i['category'] == 'workflow'])

    def test_ai_answers_are_private(self):
        self.assertEqual(self.Home.get_ai_answer(0)['state'], 'failed')
