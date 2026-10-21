from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDepartmentWorkflows(TransactionCase):
    """Department admins operate their department's workflows; administrators author them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')
        cls.lead = new_test_user(cls.env, 'wf_sales_lead', groups='workflow_center.group_workflow_department_manager')
        cls.outsider = new_test_user(cls.env, 'wf_hr_lead', groups='workflow_center.group_workflow_department_manager')
        lead_employee = cls.env['hr.employee'].create({'name': 'Sales lead', 'user_id': cls.lead.id})
        outsider_employee = cls.env['hr.employee'].create({'name': 'HR lead', 'user_id': cls.outsider.id})
        cls.sales = cls.env['hr.department'].create({'name': 'Sales', 'manager_id': lead_employee.id})
        cls.retail = cls.env['hr.department'].create({'name': 'Retail', 'parent_id': cls.sales.id})
        cls.hr = cls.env['hr.department'].create({'name': 'People', 'manager_id': outsider_employee.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Department customer'})
        model = cls.env['ir.model']._get('res.partner')
        Workflow = cls.env['workflow.definition'].with_user(cls.admin)
        cls.own = Workflow.create({'name': 'Retail follow-up', 'model_id': model.id,
                                   'department_id': cls.retail.id, 'user_id': cls.lead.id})
        cls.as_admin = Workflow.create({'name': 'Retail admin job', 'model_id': model.id,
                                        'department_id': cls.retail.id, 'user_id': cls.admin.id})
        cls.other = Workflow.create({'name': 'People onboarding', 'model_id': model.id,
                                     'department_id': cls.hr.id, 'user_id': cls.outsider.id})
        for flow in (cls.own, cls.as_admin, cls.other):
            cls.env['workflow.step'].with_user(cls.admin).create({
                'workflow_id': flow.id, 'name': 'Wait a day', 'kind': 'wait', 'wait_hours': 24, 'end': True})

    def test_department_admin_sees_only_departments_they_manage(self):
        visible = self.env['workflow.definition'].with_user(self.lead).search([])
        self.assertEqual(visible, self.own | self.as_admin, 'Sub-departments count, other departments do not')
        menu = self.env.ref('workflow_center.menu_workflows')
        self.assertIn(menu, self.env['ir.ui.menu'].with_user(self.lead).get_user_roots())
        self.assertFalse(menu.action, 'Administrators land on Templates, department managers on My workflows')

    def test_department_admin_operates_but_does_not_author(self):
        own = self.own.with_user(self.lead)
        data = own.builder_data()
        self.assertFalse(data['can_edit'])
        own.action_test_dialog()
        self.env['workflow.test'].with_user(self.lead).create(
            {'workflow_id': own.id, 'record_id': self.partner.id}).action_start()
        own.action_activate()
        self.assertEqual(own.state, 'active')
        self.assertTrue(self.own.sudo().manual_action_id, 'The run button is installed for them')
        own.action_pause()
        self.assertEqual(own.state, 'paused')
        with self.assertRaises(AccessError):
            own.write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            self.env['workflow.step'].with_user(self.lead).create(
                {'workflow_id': own.id, 'name': 'Another', 'kind': 'wait'})
        with self.assertRaises(AccessError):
            self.env['workflow.definition'].with_user(self.lead).from_template('applicant_stage_emails')

    def test_workflows_running_as_someone_else_or_elsewhere_stay_closed(self):
        with self.assertRaises(AccessError):
            self.as_admin.with_user(self.lead).action_activate()
        self.assertTrue(self.as_admin.with_user(self.lead).builder_data(), 'Visible, but not operable')
        with self.assertRaises(AccessError):
            self.other.with_user(self.lead).builder_data()
        with self.assertRaises(AccessError):
            self.other.with_user(self.lead).action_pause()
        plain = new_test_user(self.env, 'wf_plain_user', groups='base.group_user')
        self.env['hr.employee'].create({'name': 'Plain manager', 'user_id': plain.id})
        self.retail.sudo().manager_id = plain.employee_id
        with self.assertRaises(AccessError):
            self.own.with_user(plain).action_pause()

    def test_computed_filters_accept_odoo20_operators(self):
        # The web client sends ('available', '=', True), which Odoo 20 turns into 'in'.
        Template = self.env['workflow.template'].with_user(self.admin)
        result = Template.web_search_read([('available', '=', True)], {'name': {}})
        ready = Template.search([('available', 'in', [True])])
        self.assertEqual(result['length'], len(ready))
        self.assertEqual(Template.search([('available', 'not in', [True])]) | ready, Template.search([]))
        Workflow = self.env['workflow.definition'].with_user(self.lead)
        self.assertEqual(Workflow.search([('managed_by_me', 'in', [True])]), self.own | self.as_admin)
        self.assertFalse(Workflow.search([('managed_by_me', '=', False)]))
