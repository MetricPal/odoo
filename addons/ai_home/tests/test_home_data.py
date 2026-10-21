from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestHomeData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'home_data_user', groups='base.group_user,base.group_partner_manager')

    def test_my_work_lists_records_the_user_touched_newest_first(self):
        Partner = self.env['res.partner'].with_user(self.user)
        first = Partner.create({'name': 'First touched'})
        second = Partner.create({'name': 'Second touched'})
        first.message_post(body='Called the customer', message_type='comment')
        second.message_post(body='Sent the quote', message_type='comment')
        work = self.env['ai.home.item'].with_user(self.user).get_home_data()['myWork']
        names = [item['name'] for item in work]
        self.assertLess(names.index('Second touched'), names.index('First touched'))
        item = next(item for item in work if item['name'] == 'Second touched')
        self.assertEqual(item['action'], {'res_model': 'res.partner', 'res_id': second.id})
        self.assertIn('You commented', item['subtitle'])
        self.assertEqual(len(names), len(set(names)), 'One entry per record')

    def test_my_work_hides_records_the_user_can_no_longer_read(self):
        other_company = self.env['res.company'].create({'name': 'Home other company'})
        partner = self.env['res.partner'].with_user(self.user).create({'name': 'Moved away'})
        partner.message_post(body='Note', message_type='comment')
        partner.sudo().company_id = other_company
        work = self.env['ai.home.item'].with_user(self.user).get_home_data()['myWork']
        self.assertNotIn('Moved away', [item['name'] for item in work])

    def test_overdue_activity_needs_attention(self):
        partner = self.env['res.partner'].create({'name': 'Follow-up customer'})
        partner.activity_schedule('mail.mail_activity_data_todo', summary='Call back',
                                  user_id=self.user.id,
                                  date_deadline=fields.Date.today() - timedelta(days=1))
        attention = self.env['ai.home.item'].with_user(self.user).get_home_data()['attention']
        item = next(item for item in attention if item['name'] == 'Call back')
        self.assertEqual(item['tone'], 'danger')
        self.assertEqual(item['action']['res_model'], 'res.partner')

    def test_home_data_has_no_favorites(self):
        data = self.env['ai.home.item'].with_user(self.user).get_home_data()
        self.assertNotIn('favorites', data)
        self.assertNotIn('ai_home_favorites', self.env['res.users']._fields)

    def test_workflow_runs_are_listed_for_workflow_administrators(self):
        if 'workflow.run' not in self.env:
            self.skipTest('Workflows is not installed')
        from odoo.addons.workflow_center.models.workflow import internal

        admin = self.env.ref('base.user_admin')
        flow = self.env['workflow.definition'].with_user(admin).create({
            'name': 'Home run check', 'model_id': self.env['ir.model']._get('res.partner').id,
        })
        Run = internal(self.env['workflow.run'].sudo())
        failed = Run.create({'workflow_id': flow.id, 'record_id': admin.partner_id.id,
                             'name': 'Azure Interior', 'revision': 1, 'state': 'failed'})
        Run.create({'workflow_id': flow.id, 'record_id': admin.partner_id.id,
                    'name': 'Preview', 'revision': 1, 'state': 'done', 'is_test': True})
        runs = self.env['ai.home.item'].with_user(admin).get_home_data()['runs']
        item = next(item for item in runs if item['key'] == f'run-{failed.id}')
        self.assertEqual(item['name'], 'Home run check')
        self.assertEqual(item['subtitle'], 'Azure Interior')
        self.assertEqual(item['status'], 'failed')
        self.assertEqual(item['action'], {'res_model': 'workflow.run', 'res_id': failed.id})
        self.assertNotIn('Preview', [item['subtitle'] for item in runs], 'Previews are not real runs')
        self.assertEqual(self.env['ai.home.item'].with_user(self.user).get_home_data()['runs'], [])

    def test_only_usable_agents_are_offered(self):
        data = self.env['ai.home.item'].with_user(self.user).get_home_data()
        self.assertIn('agents', data)
        if 'ai.agent' not in self.env:
            self.assertEqual(data['agents'], [])
            self.assertFalse(data['canManageAgents'])
            return
        self.assertEqual(data['agents'], [], 'Users outside AI Agent see no agents')
