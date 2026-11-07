from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user

from ..models.common import internal


@tagged('post_install', '-at_install')
class TestDepartmentAI(TransactionCase):
    """ADR 0012 phase 1: department AI assistants and department AI admins."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                                'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        cls.env_patch.start()
        cls.addClassCleanup(cls.env_patch.stop)
        company = [Command.set(cls.env.company.ids)]
        cls.ai_manager = mail_new_test_user(cls.env, login='ai_mgr', groups='ai_agent.group_manager', company_ids=company)
        cls.hr_head = mail_new_test_user(cls.env, login='hr_head', groups='ai_agent.group_user', company_ids=company)
        cls.ai_admin = mail_new_test_user(cls.env, login='hr_ai_admin', groups='ai_agent.group_user', company_ids=company)
        cls.staff = mail_new_test_user(cls.env, login='hr_staff', groups='ai_agent.group_user', company_ids=company)
        cls.hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        cls.recruiting = cls.env['hr.department'].create({'name': 'Recruiting', 'parent_id': cls.hr.id})
        cls.finance = cls.env['hr.department'].create({'name': 'Finance'})
        head = cls.env['hr.employee'].create({'name': 'HR head', 'user_id': cls.hr_head.id})
        cls.hr.manager_id = head
        cls.hr.with_user(cls.ai_manager).write({'ai_admin_ids': [Command.set(cls.ai_admin.ids)]})
        cls.engine = cls.env['ai.agent.engine'].create({'name': 'Test engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'HR policy helper', 'engine_id': cls.engine.id,
                                               'department_id': cls.recruiting.id, 'access_scope': 'company'})
        cls.agent.action_activate()
        cls.finance_agent = cls.env['ai.agent'].create({'name': 'Finance helper', 'engine_id': cls.engine.id,
                                                       'department_id': cls.finance.id, 'access_scope': 'company'})

    def test_assistant_user_is_created_by_ai_managers_and_cannot_sign_in(self):
        with self.assertRaises(AccessError):
            self.hr.with_user(self.hr_head).action_create_ai_assistant()
        self.hr.with_user(self.ai_manager).action_create_ai_assistant()
        assistant = self.hr.ai_assistant_user_id
        self.assertTrue(assistant.ai_assistant)
        self.assertEqual(assistant.ai_assistant_department_id, self.hr)
        self.assertFalse(assistant.share)
        self.assertFalse(assistant.employee_ids, 'An AI assistant is not an employee')
        with self.assertRaises(UserError):
            self.hr.with_user(self.ai_manager).action_create_ai_assistant()
        with self.assertRaises(AccessDenied):
            assistant.with_user(assistant)._check_credentials({'type': 'password', 'password': 'anything'},
                                                              {'interactive': True})
        # Nobody turns a person into an assistant, or an assistant into a person, outside the department action.
        with self.assertRaises(AccessError):
            self.staff.with_user(self.ai_manager).sudo(False).write({'ai_assistant': True})
        with self.assertRaises(AccessError):
            self.hr.with_user(self.ai_manager).write({'ai_assistant_user_id': self.staff.id})

    def test_assistant_keeps_working_when_the_manager_leaves(self):
        self.hr.with_user(self.ai_manager).action_create_ai_assistant()
        assistant = self.hr.ai_assistant_user_id
        self.hr_head.active = False
        self.assertTrue(assistant.active)
        self.assertEqual(self.hr.ai_assistant_user_id, assistant)

    def test_only_ai_managers_choose_department_ai_admins(self):
        with self.assertRaises(AccessError):
            self.hr.with_user(self.hr_head).write({'ai_admin_ids': [Command.link(self.staff.id)]})
        self.hr.with_user(self.ai_manager).write({'ai_admin_ids': [Command.link(self.staff.id)]})
        self.assertIn(self.staff, self.hr.ai_admin_ids)

    def test_department_manager_and_ai_admin_configure_sub_department_agents(self):
        for person in (self.hr_head, self.ai_admin):
            agent = self.agent.with_user(person)
            self.assertTrue(agent.can_configure)
            self.assertIn(self.agent, self.env['ai.agent'].with_user(person).search([('can_configure', '=', True)]))
            self.assertNotIn(self.finance_agent,
                             self.env['ai.agent'].with_user(person).search([('can_configure', '=', True)]))
        self.assertFalse(self.agent.with_user(self.staff).can_configure)

    def test_department_changes_apply_at_once(self):
        revision = self.agent.revision
        self.agent.with_user(self.ai_admin).write({'system_prompt': 'Quote the policy you rely on.'})
        self.assertEqual(self.agent.state, 'active')
        self.assertEqual(self.agent.revision, revision + 1)
        self.assertEqual(self.agent.system_prompt, 'Quote the policy you rely on.')
        # Still usable: the change is the configuration in force, no manager review needed.
        self.agent.with_user(self.staff)._usable()

    def test_department_admins_cannot_change_connection_data_or_other_departments(self):
        with self.assertRaises(AccessError):
            self.agent.with_user(self.ai_admin).write({'max_requests_per_day': 999})
        with self.assertRaises(AccessError):
            self.agent.with_user(self.ai_admin).write({'department_id': self.finance.id})
        with self.assertRaises(AccessError):
            self.finance_agent.with_user(self.ai_admin).write({'system_prompt': 'Not my department'})
        with self.assertRaises(AccessError):
            self.agent.with_user(self.staff).write({'system_prompt': 'Not an admin'})
        with self.assertRaises(AccessError):
            self.agent.with_user(self.ai_admin).write({'state': 'paused'})

    def test_department_admin_adds_activates_and_pauses_their_agents(self):
        agent = self.env['ai.agent'].with_user(self.ai_admin).create({
            'name': 'Onboarding helper', 'engine_id': self.engine.id, 'department_id': self.hr.id,
            'access_scope': 'company', 'system_prompt': 'Help new hires.'})
        self.assertEqual(agent.department_id, self.hr)
        agent.action_activate()
        self.assertEqual(agent.state, 'active')
        agent.action_pause()
        self.assertEqual(agent.state, 'paused')
        with self.assertRaises(AccessError):
            self.env['ai.agent'].with_user(self.ai_admin).create({
                'name': 'Elsewhere', 'engine_id': self.engine.id, 'department_id': self.finance.id})
        with self.assertRaises(AccessError):
            self.env['ai.agent'].with_user(self.ai_admin).create({'name': 'No department', 'engine_id': self.engine.id})
        with self.assertRaises(AccessError):
            self.finance_agent.with_user(self.ai_admin).action_activate()

    def test_ai_managers_keep_the_review_flow(self):
        with self.assertRaises(UserError):
            self.agent.with_user(self.ai_manager).write({'system_prompt': 'Changed by a manager'})
