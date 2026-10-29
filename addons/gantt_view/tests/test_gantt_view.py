from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGanttView(TransactionCase):
    def _view(self, arch):
        return self.env['ir.ui.view'].create({'name': 'gantt test', 'model': 'res.partner', 'type': 'gantt',
                                              'arch': arch})

    def test_gantt_view_type_and_validation(self):
        view = self._view('<gantt date_start="create_date" date_stop="write_date" default_group_by="company_id" '
                          'default_scale="month"><field name="name"/></gantt>')
        self.assertEqual(view.type, 'gantt')
        self.assertIn('gantt', self.env['ir.ui.view'].get_view_info())
        with self.assertRaises(ValidationError):
            self._view('<gantt date_start="create_date"/>')
        with self.assertRaises(ValidationError):
            self._view('<gantt date_start="create_date" date_stop="no_such_field"/>')
        with self.assertRaises(ValidationError):
            self._view('<gantt date_start="create_date" date_stop="write_date" default_scale="decade"/>')
        result = self.env['res.partner'].get_views([(view.id, 'gantt')])
        self.assertIn('gantt', result['views'])

    def test_action_view_mode(self):
        action = self.env['ir.actions.act_window'].create({'name': 'Partners', 'res_model': 'res.partner',
                                                           'view_mode': 'list,gantt'})
        self.assertEqual(action.view_mode, 'list,gantt')
        self.env['ir.actions.act_window.view'].create({'act_window_id': action.id, 'view_mode': 'gantt'})
