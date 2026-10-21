"""Guided account setup and the platform cards."""

from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.providers import registry

PERSON = {'id': 'urn:li:person:SETUP', 'name': 'Setup QA', 'member': 'urn:li:person:SETUP', 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialSetup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'linkedin' not in registry.installed(cls.env):
            cls.skipTest(cls, 'Needs omni_linkedin')
        cls.manager = new_test_user(
            cls.env, login='setup_manager',
            groups='omni_channel.group_omni_manager,approval_center.group_approval_center_manager',
        )
        cls.operator = new_test_user(cls.env, login='setup_operator', groups='omni_channel.group_omni_user')
        cls.approver = new_test_user(
            cls.env, login='setup_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
        )
        cls.outsider = new_test_user(
            cls.env, login='setup_outsider', groups='base.group_user,approval_center.group_approval_center_approver',
        )
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Setup QA', 'code': 'setup_qa',
            'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id, cls.approver.id])],
        })
        cls.LinkedIn = type(registry.provider(cls.env, 'linkedin'))
        cls.linkedin_type = cls.env['omni.channel.type'].search([('code', '=', 'linkedin')])

    def _start(self):
        action = self.linkedin_type.with_user(self.manager).action_social_connect()
        self.assertEqual(action['views'][0][0], self.env.ref('omni_social.connection_setup_form').id)
        Connections = self.env['omni.social.connection'].with_user(self.manager).with_context(action['context'])
        with Form(Connections, view='omni_social.connection_setup_form') as form:
            self.assertEqual(form.provider, 'linkedin')
            self.assertEqual(form.setup_step, 'platform')
            form.account_kind = 'person'
            form.purpose_id = self.team
        return form.record

    def test_platform_cards(self):
        action = self.env.ref('omni_social.platforms')
        cards = self.env['omni.channel.type'].search(eval(action.domain))
        codes = set(cards.mapped('code'))
        self.assertIn('linkedin', codes)
        self.assertNotIn('telegram', codes, 'messaging channels belong to Omnichannel')
        ready = self.env['omni.channel.type'].search([('social_ready', '=', True)])
        self.assertIn(self.linkedin_type, ready)
        self.assertIn('3,000 characters', self.linkedin_type.social_rules)
        missing = cards - ready
        if missing:
            self.assertTrue(missing.filtered(lambda c: c.category == 'social'),
                            'platforms without a connector stay visible, dimmed')
            with self.assertRaisesRegex(UserError, 'connector module'):
                missing[0].action_social_connect()

    def test_operators_cannot_start_or_steer_setup(self):
        with self.assertRaises(AccessError):
            self.linkedin_type.with_user(self.operator).action_social_connect()
        account = self._start()
        with self.assertRaises(AccessError):
            account.with_user(self.operator).action_setup_next()

    def test_full_walkthrough(self):
        account = self._start()
        account.action_setup_next()
        self.assertEqual(account.setup_step, 'connect')

        with self.assertRaisesRegex(UserError, 'Connect the account first'):
            account.action_setup_next()
        with patch.object(self.LinkedIn, 'verify', return_value=PERSON):
            account.action_connect('synthetic')
        account.action_setup_next()
        self.assertEqual(account.setup_step, 'approval')

        self.assertIn('Choose who approves', account.approval_problem)
        with self.assertRaisesRegex(UserError, 'Choose who approves'):
            account.action_setup_next()
        dialog = account.action_new_approval_type()
        self.assertEqual(dialog['target'], 'new')
        policy = self.env['approval.center.policy'].with_user(self.manager).with_context(dialog['context']).create({
            'approver_ids': [fields.Command.create({'user_id': self.approver.id, 'required': True})],
        })
        self.assertEqual(account.approval_type_id, policy, 'the new approval type is picked for the account')
        self.assertFalse(policy.manager_approval)
        account.invalidate_recordset(['approval_problem'])
        self.assertFalse(account.approval_problem)
        account.action_setup_next()
        self.assertEqual(account.setup_step, 'receiving')

        account.action_setup_next()  # Skip for now
        self.assertEqual(account.setup_step, 'done')
        result = account.action_setup_next()
        self.assertEqual(result['views'][0][0], self.env.ref('omni_social.connection_form').id)
        account.action_setup_back()
        self.assertEqual(account.setup_step, 'receiving')

    def test_approval_problems_are_specific(self):
        account = self._start()
        policy = self.env['approval.center.policy'].create({
            'name': 'Managers', 'company_id': self.env.company.id, 'manager_approval': True,
            'approver_ids': [fields.Command.create({'user_id': self.approver.id})],
        })
        account.approval_type_id = policy
        self.assertIn("Requester's manager approves", account.approval_problem)
        policy.manager_approval = False
        policy.approver_ids = [fields.Command.clear(), fields.Command.create({'user_id': self.outsider.id})]
        account.invalidate_recordset(['approval_problem'])
        self.assertIn(self.outsider.name, account.approval_problem)
        self.assertIn('Setup QA', account.approval_problem)

    def test_existing_accounts_are_not_sent_back_into_setup(self):
        account = self.env['omni.social.connection'].with_user(self.manager).create(
            {'name': 'Old', 'provider': 'linkedin', 'account_kind': 'person', 'purpose_id': self.team.id}
        )
        self.assertEqual(account.setup_step, 'done')
        action = account.action_open_setup()
        self.assertEqual(account.setup_step, 'connect', 'an unconnected account resumes at Connect')
        self.assertEqual(action['views'][0][0], self.env.ref('omni_social.connection_setup_form').id)
