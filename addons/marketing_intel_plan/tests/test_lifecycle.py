from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = 'marketing_intel.group_mi_user'
        cls.owner = new_test_user(cls.env, 'mil_owner', name='Daniel Owner', groups=group)
        cls.hod = new_test_user(cls.env, 'mil_hod', name='Aina HOD', groups=group)
        cls.finance = new_test_user(cls.env, 'mil_fin', name='Farid Finance', groups=group)
        cls.ceo = new_test_user(cls.env, 'mil_ceo', name='Tan CEO', groups=group)
        cls.outsider = new_test_user(cls.env, 'mil_out', name='No Marketing', groups='base.group_user')
        department = cls.env['hr.department'].create({'name': 'Marketing'})
        hod_employee = cls.env['hr.employee'].create({'name': 'Aina HOD', 'user_id': cls.hod.id,
                                                      'department_id': department.id})
        department.manager_id = hod_employee
        cls.env['hr.employee'].create({'name': 'Daniel Owner', 'user_id': cls.owner.id, 'department_id': department.id})
        for role, user in (('finance', cls.finance), ('ceo', cls.ceo)):
            cls.env['mi.approver'].create({'role': role, 'user_id': user.id})
        cls.brand = cls.env['mi.brand'].create({'name': 'Lifecycle brand'})
        cls.email = cls.env.ref('marketing_intel.channel_email')

    def _plan(self, **values):
        vals = {'name': 'Year-End Sale', 'brand_id': self.brand.id, 'budget': 85000,
                'channel_ids': [Command.set(self.email.ids)]}
        vals.update(values)
        return self.env['mi.plan'].with_user(self.owner).create(vals)

    def _activity(self, plan, user):
        return plan.activity_ids.filtered(lambda a: a.user_id == user and not a.date_done)

    def test_paid_goes_hod_finance_ceo_as_activities(self):
        plan = self._plan(proposal_type='paid')
        self.assertEqual(plan.phase, 'research')
        self.assertEqual(plan.approval_route, 'HOD › Finance › CEO')
        plan.action_submit_proposal()
        self.assertEqual(plan.proposal_state, 'approval')
        hod_todo = self._activity(plan, self.hod)
        self.assertEqual(len(hod_todo), 1)
        self.assertEqual(hod_todo.activity_type_id, self.env.ref('mail.mail_activity_data_todo'))
        self.assertIn('HOD approval', hod_todo.summary)
        self.assertTrue(hod_todo.date_deadline)
        self.assertEqual(plan.phase_label, 'Market Research · HOD approval')
        self.assertIn(plan, self.env['mi.plan'].with_user(self.hod).search([('needs_me', '=', True)]))
        self.assertTrue(plan.with_user(self.hod).can_decide)
        self.assertFalse(plan.with_user(self.finance).can_decide)
        # someone else cannot approve; marking the To-Do done approves it and opens the next one
        with self.assertRaises(UserError):
            hod_todo.with_user(self.owner).action_feedback()
        hod_todo.with_user(self.hod).action_feedback(feedback='Go ahead')
        self.assertTrue(self._activity(plan, self.finance))
        self.assertEqual(plan.approval_ids.filtered(lambda a: a.role == 'hod').state, 'approved')
        # Finance approves or refuses, never requests changes
        self.assertFalse(plan.with_user(self.finance).can_request_changes)
        with self.assertRaises(UserError):
            plan.with_user(self.finance)._decide('changes', 'no')
        plan.with_user(self.finance).action_approve_proposal()
        self.assertTrue(self._activity(plan, self.ceo))
        plan.with_user(self.ceo).action_approve_proposal()
        self.assertEqual((plan.proposal_state, plan.phase), ('approved', 'planning'))
        self.assertEqual(plan.snapshot_id.version, 1)
        self.assertIn('Year-End Sale', plan.snapshot_id.body)
        left = plan.activity_ids.filtered(lambda a: 'approval' in (a.summary or '') and not a.date_done)
        self.assertFalse(left, left.mapped(lambda a: (a.summary, a.user_id.name, a.active)))

    def test_changes_go_back_to_the_owner_and_restart(self):
        plan = self._plan(proposal_type='earned')
        self.assertEqual(plan.approval_route, 'HOD › CEO')
        plan.action_submit_proposal()
        wizard = self.env['mi.plan.decision'].with_user(self.hod).create(
            {'plan_id': plan.id, 'decision': 'changes', 'comment': 'Add competitor prices'})
        wizard.action_confirm()
        self.assertEqual(plan.proposal_state, 'changes')
        self.assertTrue(any('Update the proposal' in (s or '') for s in self._activity(plan, self.owner).mapped('summary')))
        self.assertFalse(self._activity(plan, self.hod))
        plan.action_submit_proposal()
        self.assertEqual(max(plan.approval_ids.mapped('round')), 2)
        self.assertTrue(self._activity(plan, self.hod), 'resubmitted through the whole route again')

    def test_refuse_stops_the_proposal(self):
        plan = self._plan(proposal_type='owned')
        plan.action_submit_proposal()
        plan.with_user(self.hod)._decide('refuse', 'Not now')
        self.assertEqual(plan.proposal_state, 'refused')
        with self.assertRaises(UserError):
            plan.action_submit_proposal()

    def test_owner_who_is_hod_skips_the_step(self):
        plan = self.env['mi.plan'].with_user(self.hod).create({
            'name': 'HOD idea', 'brand_id': self.brand.id, 'proposal_type': 'owned',
            'channel_ids': [Command.set(self.email.ids)]})
        plan.action_submit_proposal()
        self.assertEqual(plan.approval_ids.state, 'skipped')
        self.assertEqual(plan.phase, 'planning')

    def test_paid_without_budget_skips_finance(self):
        plan = self._plan(proposal_type='paid', budget=0)
        self.assertEqual(plan.approval_route, 'HOD › CEO')

    def test_submit_needs_type_channel_and_approvers(self):
        with self.assertRaises(UserError):
            self._plan().action_submit_proposal()
        with self.assertRaises(UserError):
            self._plan(proposal_type='paid', channel_ids=[]).action_submit_proposal()
        self.env['mi.approver'].search([('role', '=', 'ceo')]).user_id = self.outsider
        with self.assertRaises(UserError):
            self._plan(proposal_type='paid').action_submit_proposal()

    def test_review_waits_for_the_proposal_and_activity_cannot_be_cancelled(self):
        plan = self._plan(proposal_type='paid')
        with self.assertRaises(UserError):
            plan.action_submit_review()
        plan.action_submit_proposal()
        with self.assertRaises(UserError):
            self._activity(plan, self.hod).with_user(self.hod).unlink()
        plan.unlink()  # deleting the campaign removes its activities

    def test_later_stages_follow_the_campaign(self):
        plan = self._plan(proposal_type='owned')
        plan.sudo().write({'phase': 'planning', 'proposal_state': 'approved'})
        plan.sudo().state = 'scheduled'
        self.assertEqual(plan.phase, 'execution')
        plan.action_done()
        self.assertEqual(plan.phase, 'results')
        plan.action_start_evaluation()
        self.assertEqual(plan.phase, 'evaluation')
        plan.action_mark_evaluated()
        self.assertEqual(plan.phase_label, 'Evaluation · Done')
        self.assertEqual(plan.action_open_spend()['domain'], [('plan_id', '=', plan.id)])
