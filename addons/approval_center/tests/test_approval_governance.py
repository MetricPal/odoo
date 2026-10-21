from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestApprovalGovernance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requester = new_test_user(cls.env, 'ac_requester', groups='approval_center.group_approval_center_user')
        cls.approver_a = new_test_user(cls.env, 'ac_approver_a', groups='approval_center.group_approval_center_approver')
        cls.approver_b = new_test_user(cls.env, 'ac_approver_b', groups='approval_center.group_approval_center_approver')
        cls.manager = new_test_user(cls.env, 'ac_manager', groups='approval_center.group_approval_center_manager,base.group_partner_manager')
        cls.policy = cls.env['approval.center.policy'].create({
            'name': 'Governance test',
            'company_id': False,
            'approval_minimum': 1,
            'has_document': 'no',
            'approver_ids': [
                (0, 0, {'user_id': cls.approver_a.id, 'sequence': 1}),
                (0, 0, {'user_id': cls.approver_b.id, 'sequence': 2}),
            ],
        })

    def _request(self, user=None, policy=None, **values):
        user = user or self.requester
        return self.env['approval.center.request'].with_user(user).create({
            'name': 'Test request', 'policy_id': (policy or self.policy).id, **values,
        })

    def _submitted(self, **kwargs):
        request = self._request(**kwargs)
        request.action_submit()
        return request

    # S1: status can only change through actions
    def test_requester_cannot_write_state(self):
        request = self._request()
        with self.assertRaises(AccessError):
            request.write({'state': 'approved'})
        with self.assertRaises(AccessError):
            request.write({'approved_at': '2026-01-01 00:00:00'})
        with self.assertRaises(AccessError):
            self.env['approval.center.request'].with_user(self.requester).create({
                'name': 'Forged', 'policy_id': self.policy.id, 'state': 'approved'})

    def test_requester_cannot_create_for_someone_else_or_link_records(self):
        Request = self.env['approval.center.request'].with_user(self.requester)
        with self.assertRaises(AccessError):
            Request.create({'name': 'X', 'policy_id': self.policy.id, 'requester_id': self.approver_a.id})
        with self.assertRaises(AccessError):
            Request.create({'name': 'X', 'policy_id': self.policy.id,
                            'target_model': 'res.partner', 'target_res_id': self.requester.partner_id.id})

    # S2: approver lines cannot be forged
    def test_requester_cannot_forge_approver_decisions(self):
        request = self._request()
        request._prepare_request_approvers()
        line = request.approver_ids[:1]
        self.assertTrue(line)
        with self.assertRaises(AccessError):
            line.with_user(self.requester).write({'status': 'approved'})
        with self.assertRaises(AccessError):
            self.env['approval.center.approver'].with_user(self.requester).create({
                'request_id': request.id, 'user_id': self.manager.id, 'status': 'approved'})
        request.action_submit()
        with self.assertRaises(UserError):
            self.env['approval.center.approver'].with_user(self.requester).create({
                'request_id': request.id, 'user_id': self.manager.id})
        with self.assertRaises(UserError):
            request.approver_ids.with_user(self.requester).unlink()

    def test_approver_cannot_write_own_line_status(self):
        request = self._submitted()
        line = request.approver_ids.filtered(lambda l: l.user_id == self.approver_a)
        with self.assertRaises(AccessError):
            line.with_user(self.approver_a).write({'status': 'approved'})

    # S3: no self-approval unless the category allows it
    def test_no_self_approval_by_default(self):
        request = self._submitted(user=self.approver_a)
        with self.assertRaises(AccessError):
            request.with_user(self.approver_a).action_approve()
        manager_request = self._submitted(user=self.manager)
        with self.assertRaises(AccessError):
            manager_request.with_user(self.manager).action_approve()

    def test_self_approval_when_category_allows(self):
        self.policy.allow_self_approval = True
        request = self._submitted(user=self.approver_a)
        request.with_user(self.approver_a).action_approve()
        self.assertEqual(request.state, 'approved')

    def test_manager_override_is_audited(self):
        request = self._submitted()
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertIn('override', request.audit_ids.filtered(lambda a: a.event == 'approved').message.lower())

    # B1: sequence enforced
    def test_sequence_enforced(self):
        self.policy.approver_sequence = True
        self.policy.approval_minimum = 2
        request = self._submitted()
        self.assertEqual(request.waiting_for, self.approver_a.name)
        with self.assertRaises(UserError):
            request.with_user(self.approver_b).action_approve()
        request.with_user(self.approver_a).action_approve()
        self.assertEqual(request.state, 'submitted')
        request.with_user(self.approver_b).action_approve()
        self.assertEqual(request.state, 'approved')

    def test_double_decision_rejected(self):
        self.policy.approval_minimum = 2
        request = self._submitted()
        request.with_user(self.approver_a).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.approver_a).action_approve()

    # B2: required approvers enforced
    def test_required_approver_must_approve(self):
        self.policy.approver_ids.filtered(lambda l: l.user_id == self.approver_b).required = True
        request = self._submitted()
        request.with_user(self.approver_a).action_approve()
        self.assertEqual(request.state, 'submitted', 'Minimum reached but required approver pending')
        request.with_user(self.approver_b).action_approve()
        self.assertEqual(request.state, 'approved')

    def test_minimum_frozen_at_submission(self):
        request = self._submitted()
        self.policy.approval_minimum = 2
        request.with_user(self.approver_a).action_approve()
        self.assertEqual(request.state, 'approved')

    # Content frozen after submission
    def test_submitted_content_is_frozen(self):
        request = self._submitted(amount=10)
        with self.assertRaises(UserError):
            request.with_user(self.requester).write({'amount': 1000})
        request.with_user(self.requester).action_cancel()
        self.assertEqual(request.state, 'to_submit')
        self.assertEqual(set(request.approver_ids.mapped('status')), {'new'})
        request.with_user(self.requester).write({'amount': 1000})

    # S4: audit retention
    def test_audit_cannot_be_erased(self):
        draft = self._request()
        draft.unlink()
        request = self._submitted()
        with self.assertRaises(UserError):
            request.with_user(self.requester).unlink()
        with self.assertRaises(AccessError):
            request.audit_ids.with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            request.audit_ids.with_user(self.manager).write({'message': 'rewritten'})
        with self.assertRaises(AccessError):
            self.env['approval.center.audit'].with_user(self.manager).create({
                'request_id': request.id, 'event': 'approved', 'actor_id': self.manager.id})
        request.with_user(self.requester).action_cancel()
        with self.assertRaises(UserError):
            request.with_user(self.requester).unlink()
        request.with_user(self.requester).action_archive()
        self.assertFalse(request.active)

    # S5: execution target and method
    def test_action_name_requires_model_and_public_action(self):
        with self.assertRaises(ValidationError):
            self.policy.write({'action_name': 'action_archive'})
        partner_model = self.env.ref('base.model_res_partner')
        with self.assertRaises(ValidationError):
            self.policy.write({'model_id': partner_model.id, 'action_name': 'unlink'})
        with self.assertRaises(ValidationError):
            self.policy.write({'model_id': partner_model.id, 'action_name': 'action_does_not_exist'})
        self.policy.write({'model_id': partner_model.id, 'action_name': 'action_archive'})

    def _executable_request(self):
        partner = self.env['res.partner'].create({'name': 'Execution target'})
        self.policy.write({'model_id': self.env.ref('base.model_res_partner').id, 'action_name': 'action_archive'})
        request = self.env['approval.center.request'].with_user(self.manager).create({
            'name': 'Archive partner', 'policy_id': self.policy.id,
            'target_model': 'res.partner', 'target_res_id': partner.id,
        })
        request.action_submit()
        request.with_user(self.approver_a).action_approve()
        return request, partner

    def test_execution_runs_once(self):
        request, partner = self._executable_request()
        request.with_user(self.manager).action_execute()
        self.assertFalse(partner.active)
        self.assertTrue(request.executed_at)
        with self.assertRaises(UserError):
            request.with_user(self.manager).action_execute()
        with self.assertRaises(UserError):
            request.with_user(self.manager).action_cancel()

    def test_failed_execution_keeps_audit(self):
        request, partner = self._executable_request()
        partner.unlink()
        result = request.with_user(self.manager).action_execute()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertTrue(request.failure_reason)
        self.assertFalse(request.executed_at)
        self.assertIn('failed', request.audit_ids.mapped('event'))

    def test_only_requester_or_manager_executes(self):
        request, _partner = self._executable_request()
        with self.assertRaises(AccessError):
            request.with_user(self.approver_a).action_execute()

    def test_cannot_execute_unapproved(self):
        request = self._submitted()
        with self.assertRaises(UserError):
            request.with_user(self.requester).action_execute()

    # Multi-company boundary
    def test_requests_hidden_across_companies(self):
        other = self.env['res.company'].create({'name': 'Other approvals company'})
        self.manager.write({'company_ids': [(4, other.id)]})
        request = self.env['approval.center.request'].with_user(self.manager).with_company(other).create({
            'name': 'Other company request', 'policy_id': self.policy.id, 'company_id': other.id})
        visible = self.env['approval.center.request'].with_user(self.manager).with_context(
            allowed_company_ids=[self.env.company.id]).search([('id', '=', request.id)])
        self.assertFalse(visible)
