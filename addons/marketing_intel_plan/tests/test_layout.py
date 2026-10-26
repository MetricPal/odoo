from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPanelLayout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.marketer = new_test_user(cls.env, 'mil_marketer', groups='marketing_intel.group_mi_user')
        cls.manager = new_test_user(cls.env, 'mil_manager', groups='marketing_intel.group_mi_manager')
        cls.Layout = cls.env['mi.panel.layout']
        cls.env['mi.panel.layout'].search([('user_id', '=', False)]).unlink()
        report = cls.env['report.studio.report'].with_user(cls.marketer).create({'name': 'Leads report'})
        cls.box = cls.env['report.studio.block'].with_user(cls.marketer).create({
            'report_id': report.id, 'type': 'kpi', 'title': 'Partners', 'res_model': 'res.partner'})

    def keys(self, user):
        return [b['key'] for b in self.env['mi.panel'].with_user(user).get_panel()['layout']['blocks']]

    def test_defaults_per_role_and_personal_view(self):
        self.assertEqual(self.Layout.with_user(self.manager)._user_role(), 'manager')
        layout = self.Layout.with_user(self.marketer)
        layout.choose_view('marketer')
        keys = self.keys(self.marketer)
        self.assertEqual(keys[:2], ['kpis', 'timeline'])
        layout.save_layout([{'key': 'campaigns', 'width': 'full'}, {'key': 'todos', 'width': 'half'},
                            {'key': 'todos', 'width': 'half'}, {'key': 'nonsense'},
                            {'key': 'report', 'report_block_id': self.box.id, 'width': 'bogus'}])
        panel = self.env['mi.panel'].with_user(self.marketer).get_panel()
        blocks = panel['layout']['blocks']
        self.assertEqual([b['key'] for b in blocks], ['campaigns', 'todos', 'report'])
        self.assertEqual(blocks[2]['width'], 'half')
        self.assertEqual(blocks[2]['box']['title'], 'Partners')
        self.assertTrue(blocks[2]['box']['display'])
        self.assertEqual(panel['layout']['view'], 'mine')
        with self.assertRaises(UserError):
            layout.save_layout([])
        # switch to the role view and back
        layout.choose_view('marketer')
        self.assertEqual(self.keys(self.marketer)[:2], ['kpis', 'timeline'])
        layout.choose_view('mine')
        self.assertEqual(self.keys(self.marketer)[0], 'campaigns')
        layout.reset_mine()
        self.assertEqual(self.keys(self.marketer)[0], 'kpis')
        self.assertEqual(self.env['mi.panel'].with_user(self.marketer).get_panel()['layout']['boxes'][0]['title'],
                         'Partners')

    def test_only_managers_save_role_views(self):
        with self.assertRaises(AccessError):
            self.Layout.with_user(self.marketer).save_layout([{'key': 'alerts', 'width': 'full'}], scope='role',
                                                              role='marketer')
        self.Layout.with_user(self.manager).save_layout([{'key': 'alerts', 'width': 'full'},
                                                         {'key': 'kpis', 'width': 'full'}], scope='role', role='marketer')
        self.Layout.with_user(self.marketer).choose_view('marketer')
        self.assertEqual(self.keys(self.marketer), ['alerts', 'kpis'])
        self.assertEqual(self.Layout.search_count([('user_id', '=', False), ('role', '=', 'marketer')]), 1)
