from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
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

    def test_greeting_line(self):
        data = self._data()
        self.assertEqual(data['firstName'], 'Daniel')
        self.assertTrue(data['roleLabel'])
        self.assertEqual(data['summary'], 'nothing needs you right now')

    def test_overdue_activity_needs_attention_with_buttons(self):
        activity = self._call_back()
        data = self._data()
        item = next(item for item in data['attention'] if item['title'] == 'Call back Lim Trading')
        self.assertEqual(item['category'], 'activity')
        self.assertEqual(item['tag'], 'Overdue')
        self.assertTrue(item['overdue'])
        self.assertIn('due yesterday', item['meta'])
        self.assertEqual((item['primary']['method'], item['secondary']['method']),
                         ('action_done', 'action_reschedule_tomorrow'))
        self.assertEqual((item['model'], item['resId']), ('mail.activity', activity.id))
        self.assertEqual(item['openModel'], 'res.partner', 'opening an activity opens its document')
        self.assertEqual(data['summary'], '1 item needs you, 1 overdue')

    def test_my_activities_tile_follows_odoo_activity_colours(self):
        tile = next(t for t in self._data()['live'] if t['key'] == 'activities')
        self.assertEqual((tile['label'], tile['value'], tile['tone']), ('My activities', '0', 'good'))
        self._call_back(days=0)
        tile = next(t for t in self._data()['live'] if t['key'] == 'activities')
        self.assertEqual((tile['value'], tile['sub'], tile['tone']), ('1', '1 due today', 'warn'))
        self._call_back(days=2)
        tile = next(t for t in self._data()['live'] if t['key'] == 'activities')
        self.assertEqual((tile['value'], tile['sub'], tile['tone']), ('2', '1 overdue · 1 today', 'bad'))
        self.assertEqual(tile['action']['res_model'], 'mail.activity')
        self.assertEqual(tile['action']['domain'], [('user_id', '=', self.user.id)])

    def test_buttons_run_as_the_user(self):
        activity = self._call_back()
        self.Home.run_home_action('mail.activity', activity.id, 'action_reschedule_tomorrow')
        self.assertEqual(activity.date_deadline, fields.Date.today() + timedelta(days=1))
        self.Home.run_home_action('mail.activity', activity.id, 'action_done')
        self.assertFalse(activity.exists().filtered('active'))
        self.assertNotIn('Call back Lim Trading', [item['title'] for item in self._data()['attention']])

    def test_only_listed_buttons_can_run(self):
        partner = self.env['res.partner'].create({'name': 'Not a button'})
        with self.assertRaises(UserError):
            self.Home.run_home_action('res.partner', partner.id, 'unlink')
        with self.assertRaises(UserError):
            self.Home.run_home_action('mail.activity', 0, 'action_done')

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
        self.assertLessEqual(len(recent), 4)

    def test_recently_opened_hides_records_the_user_can_no_longer_read(self):
        other_company = self.env['res.company'].create({'name': 'Home other company'})
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Moved away'})
        partner.message_post(body='Note', message_type='comment')
        partner.sudo().company_id = other_company
        self.assertNotIn('Moved away', [item['name'] for item in self._data()['recent']])
        self.assertNotIn('Moved away', ' '.join(item['text'] for item in self._data()['feed']))

    def test_what_just_happened_marks_my_own_changes(self):
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Tan Holdings'})
        partner.message_post(body='Agreed the delivery date', message_type='comment')
        feed = self._data()['feed']
        entry = next(entry for entry in feed if 'Agreed the delivery date' in entry['text'])
        self.assertEqual((entry['actor'], entry['scope']), ('You', 'mine'))
        self.assertIn('Tan Holdings', entry['text'])
        self.assertFalse([entry for entry in feed if entry['model'].startswith('ir.')], 'no configuration records')

    def test_my_day_counts_tasks_due_today(self):
        self._call_back(days=0)
        day = self._data()['day']
        self.assertIn({'key': 'due', 'time': 'Today', 'text': '1 task due', 'model': False, 'resId': False}, day)

    def test_without_an_assistant_quick_actions_show(self):
        data = self._data()
        self.assertEqual(data['agents'], [], 'Users outside AI Agent see no agents')
        self.assertEqual(data['prompts'], [])
        self.assertIn('Contact', [quick['label'] for quick in data['quickActions']])
        self.assertTrue(all(self.env[quick['model']].with_user(self.user).has_access('create')
                            for quick in data['quickActions']))

    def test_live_tiles_need_read_access(self):
        tiles = self._data()['live']
        for tile in tiles:
            self.assertEqual(set(tile), {'key', 'label', 'value', 'sub', 'tone', 'action'})
            if tile['action']:
                self.assertTrue(self.env[tile['action']['res_model']].with_user(self.user).has_access('read'))
        self.assertNotIn('workflows', [tile['key'] for tile in tiles], 'workflow tiles are for administrators')

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
