from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestApprovalSetup(TransactionCase):
    """A new admin can tell which approval types work and fix the others."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requester = new_test_user(cls.env, 'ac_setup_requester', groups='approval_center.group_approval_center_user')
        cls.boss = new_test_user(cls.env, 'ac_setup_boss', groups='approval_center.group_approval_center_approver')
        cls.manager = new_test_user(cls.env, 'ac_setup_manager', groups='approval_center.group_approval_center_manager')
        cls.empty = cls.env['approval.center.policy'].create({
            'name': 'Empty type', 'company_id': False, 'has_document': 'no'})

    def test_type_without_approvers_needs_setup(self):
        empty = self.empty.with_user(self.requester)
        self.assertEqual(empty.setup_state, 'needs_approvers')
        self.assertEqual(empty.approval_summary, 'No approvers yet')
        notice = empty.action_card_click()
        self.assertEqual(notice['tag'], 'display_notification')
        self.assertEqual(self.empty.with_user(self.manager).action_card_click()['res_id'], self.empty.id)
        request = self.env['approval.center.request'].with_user(self.requester).create(
            {'name': 'Desk', 'policy_id': self.empty.id})
        with self.assertRaisesRegex(UserError, 'Nobody can approve "Empty type" requests for you yet'):
            request.action_submit()

    def test_approvers_or_manager_make_a_type_ready(self):
        self.empty.write({'approver_ids': [(0, 0, {'user_id': self.boss.id})]})
        self.assertEqual(self.empty.with_user(self.requester).setup_state, 'ready')
        self.assertIn(self.boss.name, self.empty.approval_summary)
        self.assertIn('1 of 1 must approve', self.empty.approval_summary)
        self.assertEqual(self.empty.with_user(self.requester).action_card_click()['res_model'],
                         'approval.center.request')

        by_manager = self.env['approval.center.policy'].create({
            'name': 'Manager type', 'company_id': False, 'has_document': 'no', 'manager_approval': True})
        self.assertEqual(by_manager.with_user(self.requester).setup_state, 'needs_approvers',
                         'No manager on the employee record yet')
        boss_employee = self.env['hr.employee'].create({'name': 'Boss', 'user_id': self.boss.id})
        self.env['hr.employee'].create({'name': 'Requester', 'user_id': self.requester.id,
                                        'parent_id': boss_employee.id})
        by_manager.invalidate_recordset(['setup_state'])
        self.assertEqual(by_manager.with_user(self.requester).setup_state, 'ready')
        self.assertIn("Requester's manager", by_manager.approval_summary)

    def test_new_request_starts_from_the_type_picker(self):
        action = self.env['approval.center.request'].with_user(self.requester).action_pick_type()
        self.assertEqual(action['res_model'], 'approval.center.policy')
        self.assertIn('kanban', action['view_mode'])

    def test_shipped_types_use_the_requester_manager(self):
        shipped = self.env['approval.center.policy'].search([]).filtered(
            lambda policy: policy.get_external_id()[policy.id].startswith('approval_center.approval_type_'))
        self.assertTrue(shipped)
        self.assertTrue(all(shipped.mapped('manager_approval')))
        data = self.env['ir.model.data'].search([('module', '=', 'approval_center'),
                                                 ('model', '=', 'approval.center.policy')])
        self.assertTrue(all(data.mapped('noupdate')), 'Upgrades must not reset admin changes')
