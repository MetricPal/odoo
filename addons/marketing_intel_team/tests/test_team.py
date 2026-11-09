from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

APP_GROUPS = ['mass_mailing.group_mass_mailing_user', 'approval_center.group_approval_center_approver']


@tagged('post_install', '-at_install')
class TestMarketingTeam(TransactionCase):
    """ADR 0016: roles, the senior review, release within limits (board 5.1, 5.2) and role panels (6.1 to 6.3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, default_phase='planning', default_proposal_state='approved'))
        groups = [g for g in APP_GROUPS if cls.env.ref(g, raise_if_not_found=False)]

        def person(login, group):
            return new_test_user(cls.env, login, name=login.replace('_', ' ').title(),
                                 groups=','.join([group] + groups))
        cls.hod = person('mt_hod', 'marketing_intel_team.group_mi_hod')
        cls.senior = person('mt_senior', 'marketing_intel_team.group_mi_senior')
        cls.junior = person('mt_junior', 'marketing_intel.group_mi_user')
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        # The marketing department: where most people with Marketing access work (this test's three people).
        cls.env['hr.employee'].sudo().search([('user_id.all_group_ids', 'in', cls.env.ref('marketing_intel.group_mi_user').ids)]).department_id = False
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io'})
        if 'mailing.list' in cls.env:
            lists = cls.env['mailing.list'].sudo().create({'name': 'metric.io subscribers'})
            cls.brand.account_ids = [Command.create({'account': f'mailing.list,{lists.id}'})]
        cls.channels = cls.env['mi.channel'].search([('code', 'in', ('email', 'sms'))])
        Employee = cls.env['hr.employee'].sudo()
        cls.department = cls.env['hr.department'].sudo().create({'name': 'Marketing',
                                                                 'mi_senior_budget_limit': 20000})
        cls.e_hod = Employee.create({'name': 'Head', 'user_id': cls.hod.id, 'department_id': cls.department.id})
        cls.department.manager_id = cls.e_hod
        cls.e_senior = Employee.create({'name': 'Senior', 'user_id': cls.senior.id, 'department_id': cls.department.id,
                                        'parent_id': cls.e_hod.id})
        cls.e_junior = Employee.create({'name': 'Junior', 'user_id': cls.junior.id, 'department_id': cls.department.id,
                                        'parent_id': cls.e_senior.id})

    def _campaign(self, owner, budget=1000, name='Spring offer'):
        if 'mailing.mailing' not in self.env:
            self.skipTest('Email Marketing is needed')
        return self.env['mi.plan'].with_user(owner).create({
            'brand_id': self.brand.id, 'name': name, 'message': 'Spring offer: 10% off.', 'budget': budget,
            'channel_ids': [Command.set(self.channels.ids)]})

    # -- roles --------------------------------------------------------------------------------------------------
    def test_the_role_is_the_marketing_access_right(self):
        self.assertTrue(self.hod.has_group('marketing_intel_team.group_mi_senior'), 'HOD ⊃ Senior ⊃ Junior')
        self.assertEqual(self.e_junior.mi_role, 'junior')
        self.e_junior.with_user(self.hod).mi_role = 'senior'
        self.assertTrue(self.junior.has_group('marketing_intel_team.group_mi_senior'))
        self.department.with_user(self.hod).write({'mi_member_ids': [Command.update(self.e_junior.id, {'mi_role': 'junior'})]})
        self.assertFalse(self.junior.has_group('marketing_intel_team.group_mi_senior'), 'set through the department')
        self.assertTrue(self.junior.has_group('marketing_intel.group_mi_user'))
        with self.assertRaises(AccessError):
            self.e_junior.with_user(self.senior).mi_role = 'senior'
        with self.assertRaises(AccessError):
            self.e_junior.with_user(self.hod).mi_role = 'hod'
        self.assertEqual(self.department.mi_hod_user_id, self.hod)
        self.assertTrue(self.department.mi_is_marketing, 'found from where the Marketing people work')
        self.assertEqual(self.env['hr.department'].search([('mi_is_marketing', '=', True)]), self.department)
        self.assertEqual(self.department._senior_for(self.junior), self.senior)
        self.assertEqual(self.department._senior_for(self.senior), self.hod)
        self.assertEqual(self.e_senior.mi_reviews_label, 'Junior')
        self.department.with_user(self.hod).mi_senior_audience_limit = 5000
        self.assertEqual(self.department.mi_senior_audience_limit, 5000)
        self.assertEqual(self.env.ref('marketing_intel.group_mi_user').name, 'Junior')

    # -- the review chain ---------------------------------------------------------------------------------------
    def test_a_juniors_campaign_goes_to_the_senior_who_releases_it_within_limits(self):
        plan = self._campaign(self.junior)
        self.assertTrue(plan.needs_senior_review)
        plan.action_submit_review()
        self.assertEqual((plan.state, plan.senior_review_state, plan.senior_reviewer_id),
                         ('review', 'waiting', self.senior))
        self.assertEqual(plan.senior_request_id.approver_ids.user_id, self.senior)
        self.assertFalse(plan.review_request_id, 'nothing is submitted in the apps before the senior accepts')
        self.assertIn('Waiting for the senior review', plan.next_step)
        senior_view = plan.with_user(self.senior)
        self.assertTrue(senior_view.can_senior_decide)
        self.assertTrue(senior_view.needs_me)
        self.assertTrue(senior_view.within_limits)
        senior_view.action_senior_accept()
        self.assertEqual(plan.senior_review_state, 'accepted')
        self.assertEqual(plan.review_request_id.policy_id.name, 'Marketing: release within limits')
        self.assertEqual(plan.review_request_id.approver_ids.user_id, self.senior)
        self.assertEqual(plan.review_request_id.state, 'approved')
        self.assertIn(plan.state, ('scheduled', 'live'), 'released by the senior')

    def test_above_the_limits_the_head_of_department_releases(self):
        plan = self._campaign(self.junior, budget=32000)
        plan.action_submit_review()
        senior_view = plan.with_user(self.senior)
        self.assertFalse(senior_view.within_limits)
        self.assertIn('above the limit', senior_view.limit_note)
        senior_view.action_senior_accept()
        request = plan.review_request_id
        self.assertEqual((request.policy_id.name, request.approver_ids.user_id, request.state),
                         ('Marketing campaign', self.hod, 'submitted'))
        self.assertEqual(plan.state, 'review')
        plan.with_user(self.hod).action_approve_review()
        self.assertIn(plan.state, ('scheduled', 'live'))

    def test_request_changes_sends_it_back_with_the_comment(self):
        plan = self._campaign(self.junior)
        plan.action_submit_review()
        action = plan.with_user(self.senior).action_senior_changes()
        wizard = self.env[action['res_model']].with_user(self.senior).create(
            {'plan_id': plan.id, 'comment': 'Shorter SMS opening, please.'})
        wizard.action_confirm()
        self.assertEqual((plan.state, plan.senior_review_state), ('content', 'changes'))
        todo = self.env['mail.activity'].search([('res_model', '=', 'mi.plan'), ('res_id', '=', plan.id),
                                                 ('user_id', '=', self.junior.id)])
        self.assertIn('Shorter SMS opening', ''.join(str(note or '') for note in todo.mapped('note')))
        with self.assertRaises(AccessError):
            plan.with_user(self.hod).action_senior_accept()

    def test_a_senior_releases_their_own_campaign_within_limits(self):
        plan = self._campaign(self.senior)
        self.assertFalse(plan.needs_senior_review)
        plan.action_submit_review()
        self.assertEqual(plan.review_request_id.approver_ids.user_id, self.senior)
        self.assertIn(plan.state, ('scheduled', 'live'))
        big = self._campaign(self.senior, budget=50000, name='Big launch')
        big.action_submit_review()
        self.assertEqual((big.state, big.review_request_id.approver_ids.user_id), ('review', self.hod))

    def test_without_a_marketing_department_nothing_changes(self):
        (self.e_hod | self.e_senior | self.e_junior).department_id = False
        plan = self._campaign(self.junior)
        self.assertFalse(plan.needs_senior_review)
        self.assertTrue(plan.within_limits)
        policy = self.env.ref('marketing_intel_plan.policy_campaign')
        policy.write({'company_id': self.env.company.id,
                      'approver_ids': [Command.clear(), Command.create({'user_id': self.hod.id})]})
        plan.action_submit_review()
        self.assertEqual(plan.review_request_id.policy_id, policy)
        self.assertEqual(plan.senior_review_state, 'none')

    def test_a_junior_without_a_senior_is_told_who_sets_it(self):
        self.e_junior.parent_id = False
        self.department.manager_id = False
        plan = self._campaign(self.junior)
        with self.assertRaises(UserError) as error:
            plan.action_submit_review()
        self.assertIn('Department', str(error.exception))

    # -- role panels ------------------------------------------------------------------------------------------
    def test_each_role_opens_on_its_view(self):
        Layout = self.env['mi.panel.layout']
        self.assertEqual(Layout.with_user(self.junior)._user_role(), 'junior')
        self.assertEqual(Layout.with_user(self.senior)._user_role(), 'senior')
        self.assertEqual(Layout.with_user(self.hod)._user_role(), 'hod')
        for user, keys in ((self.junior, {'prepared', 'going_out', 'my_results', 'make'}),
                           (self.senior, {'team_tiles', 'reviews_waiting', 'channel_performance'}),
                           (self.hod, {'dept_tiles', 'automation_health', 'team_table', 'approvals_waiting'})):
            data = self.env['mi.panel'].with_user(user).get_panel(brand_id=self.brand.id)
            shown = {block['key'] for block in data['layout']['blocks']}
            self.assertTrue(keys <= shown, (user.login, keys - shown))
            self.assertTrue(keys <= set(data['extra']), (user.login, keys - set(data['extra'])))

    def test_the_department_view_lists_what_blocks_campaigns(self):
        bare = self.env['mi.brand'].sudo().create({'name': 'No accounts yet'})
        data = self.env['mi.panel'].with_user(self.hod).get_panel()
        setup = data['extra'].get('setup')
        self.assertTrue(setup and setup['warning'])
        self.assertIn('No accounts yet', ' '.join(row['title'] for row in setup['rows']))
        team = data['extra']['team_table']
        self.assertEqual(len(team['table_rows']), 3)
        self.assertIn(bare.id, [row.get('res_id') for row in setup['rows']])

    def test_a_senior_sees_the_review_waiting_for_them(self):
        plan = self._campaign(self.junior)
        plan.action_submit_review()
        data = self.env['mi.panel'].with_user(self.senior).get_panel(brand_id=self.brand.id)
        rows = data['extra']['reviews_waiting']['rows']
        self.assertIn(plan.id, [row['res_id'] for row in rows])
        self.assertEqual(data['extra']['team_tiles']['tiles'][0]['value'], '1')

    def test_explain_this_asks_the_assistant_with_the_blocks_numbers(self):
        if 'ai.agent.run' not in self.env:
            self.skipTest('AI Agent is needed')
        asked = {}

        def fake_ask(Run, agent, prompt, **kwargs):
            asked.update(prompt=prompt, caller=kwargs.get('caller'))
            return Run.browse()
        agent = self.env['ai.agent'].sudo().search([], limit=1) or self.env['ai.agent'].browse()
        if not agent:
            self.skipTest('An AI agent is needed')
        self.brand.sudo().ai_agent_id = agent
        with patch.object(type(self.env['ai.agent.run']), '_ask', fake_ask):
            self.env['mi.panel'].with_user(self.senior).explain_block('channel_performance', brand_id=self.brand.id)
        self.assertEqual(asked['caller'], 'marketing')
        self.assertIn('My team', asked['prompt'])
        self.assertIn('Channel', asked['prompt'])
        with self.assertRaises(UserError):
            self.env['mi.panel'].with_user(self.senior).explain_block('team_table')

    def test_the_marketing_menu_has_only_the_pages_of_board_7(self):
        """Board 7 (2026-11-09): pages shown on their own form leave the menu; each page is titled like its item."""
        ref = self.env.ref
        for xmlid in ('marketing_intel.menu_competitors', 'marketing_intel.menu_sources', 'marketing_intel.menu_runs',
                      'marketing_intel_plan.menu_goals', 'marketing_intel_work.menu_proofs',
                      'marketing_intel_flow.menu_flows', 'marketing_intel_flow.menu_runs',
                      'marketing_intel_consent.menu_records', 'marketing_intel_assistant.menu_assistant'):
            self.assertFalse(ref(xmlid, raise_if_not_found=False), xmlid)
        workflows = ref('marketing_intel_flow.menu_flows_root')
        self.assertEqual(workflows.action, ref('marketing_intel_flow.action_flows'))
        self.assertFalse(workflows.child_id, 'Workflows opens the workflows directly')
        templates = ref('marketing_intel_flow.menu_recipes')
        self.assertEqual((templates.name, templates.parent_id), ('Workflow templates', ref('marketing_intel.menu_setup')))
        self.assertEqual(ref('marketing_intel_flow.action_recipes').name, 'Workflow templates')
        self.assertEqual(ref('marketing_intel_work.action_campaign_tasks').name, 'Tasks')
        self.assertEqual(ref('marketing_intel.menu_insights').child_id.sorted('sequence').mapped('name'),
                         ['Suggested campaigns', 'Market changes', 'Risks'])
        consent = ref('marketing_intel_consent.menu_consent_root', raise_if_not_found=False)
        if consent:
            self.assertEqual(consent.name, 'Consent')
            self.assertEqual(consent.child_id.sorted('sequence').mapped('name'), ['People', 'Data requests'])

    def test_without_a_manager_nobody_is_head_of_department(self):
        """Board 7: the head of department is the department manager only (no proposal approver stands in)."""
        department = self.env['hr.department'].create({'name': 'No manager'})
        self.assertFalse(department.mi_hod_user_id)
        self.assertEqual(department.mi_hod_label, "Nobody: set the department's manager")
