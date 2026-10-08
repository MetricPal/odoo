from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged

from .test_foundation import HealthyAdapter, TestOmniFoundation


@tagged('post_install', '-at_install')
class TestOmniAdministration(TestOmniFoundation):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='omni_technical_admin', groups='base.group_system')

    def test_technical_navigation_and_no_launcher(self):
        root = self.env.ref('omni_channel.menu_omni_technical')
        email = self.env.ref('base.menu_email')
        self.assertEqual(root.parent_id, email.parent_id)
        self.assertEqual(root.parent_id, self.env.ref('base.menu_custom'))
        siblings = root.parent_id.child_id.sorted(lambda menu: (menu.sequence, menu.id))
        position = siblings.ids.index(root.id)
        self.assertEqual(siblings[position + 1], email)
        self.assertLess(siblings.ids.index(self.env.ref('mail.mail_menu_technical').id), position)
        self.assertLess(siblings.ids.index(self.env.ref('mail.menu_mail_activities_section').id), position)
        self.assertEqual(root.child_id.sorted('sequence').mapped('name'),
                         ['Channels', 'Messages', 'Policies', 'Blocklist'])
        self.assertNotIn(root, self.env['ir.ui.menu'].with_user(self.admin).get_user_roots())
        visible = self.env['ir.ui.menu'].with_user(self.admin)._visible_menu_ids(debug=True)
        self.assertTrue(set((root | root.child_id).ids) <= visible)
        for user in (self.manager, self.operator):
            visible = self.env['ir.ui.menu'].with_user(user)._visible_menu_ids(debug=True)
            self.assertFalse(set((root | root.child_id).ids) & visible)
        with self.assertRaises(AccessError):
            self.env['ir.ui.menu'].with_user(self.portal)._visible_menu_ids(debug=True)
        module = self.env['ir.module.module'].search([('name', '=', 'omni_channel')])
        self.assertFalse(module.application)
        self.assertNotIn('omni.setup', self.env.registry.models)
        for xmlid in ('menu_omni_root', 'menu_setup', 'menu_configuration', 'action_setup', 'action_overview'):
            self.assertFalse(self.env.ref('omni_channel.' + xmlid, raise_if_not_found=False))

    def test_channel_shortcuts_scoped_and_authorized(self):
        channel = self.channel.with_user(self.admin)
        action = channel.action_connections()
        self.assertEqual(action['context']['default_company_id'], channel.company_id.id)
        self.assertEqual(action['context']['default_purpose_id'], channel.purpose_id.id)
        self.assertEqual(action['context']['default_channel_type_id'], channel.channel_type_id.id)
        self.assertEqual(self.env[action['res_model']].search(action['domain']), self.account)
        for method in ('action_messages', 'action_policies', 'action_delivery_logs',
                       'action_intake_logs', 'action_recipient_authorizations', 'action_audit_logs'):
            action = getattr(channel, method)()
            self.env[action['res_model']].search(action['domain'])
            with self.assertRaises(AccessError):
                getattr(self.channel.with_user(self.operator), method)()
        self.assertFalse(channel.dispatch_enabled)
        self.assertFalse(self.sender.is_selected)

    def test_generic_channel_configuration(self):
        for channel_type in self.env['omni.channel.type'].search([]):
            if channel_type == self.type:
                continue
            with self.subTest(channel=channel_type.code):
                channel = self.env['omni.channel'].with_user(self.admin).create({
                    'name': channel_type.name, 'purpose_id': self.purpose.id,
                    'channel_type_id': channel_type.id,
                })
                defaults = channel.action_connections()['context']
                account = self.env['omni.account'].with_user(self.admin).create({
                    'name': 'Connection', 'purpose_id': defaults['default_purpose_id'],
                    'company_id': defaults['default_company_id'],
                    'channel_type_id': defaults['default_channel_type_id'],
                    'namespace': 'technical-' + channel_type.code,
                    'external_account_key': 'technical-' + channel_type.code,
                })
                sender = self.env['omni.outbound.sender'].with_user(self.admin).create({
                    'name': 'Sender', 'channel_id': channel.id,
                    'account_id': account.id, 'external_key': 'sender',
                })
                with patch('odoo.addons.omni_channel.models.foundation.get_adapter', return_value=HealthyAdapter()):
                    sender.action_activate(channel.generation)
                self.assertTrue(sender.is_selected)
                self.assertFalse(channel.dispatch_enabled)

    def test_existing_business_entry_remains_available(self):
        self.assertEqual(self.env['omni.channel'].with_user(self.admin).action_open_workspace()['res_model'], 'omni.channel')
        self.assertEqual(self.env['omni.channel'].with_user(self.operator).action_open_workspace()['res_model'], 'omni.conversation')
        with self.assertRaises(AccessError):
            self.env['omni.channel'].with_user(self.portal).action_open_workspace()

    def test_block_connection_fills_scope_and_rejects_mismatch(self):
        block = self.env['omni.blocked.identity'].with_user(self.admin).create({
            'connection_id': self.account.id, 'external_key': '12345',
            'reason': 'Unwanted messages',
        })
        self.assertEqual(block.namespace, self.account.namespace)
        self.assertEqual(block.purpose_id, self.account.purpose_id)
        self.assertEqual(block.state, 'draft')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            block.write({'namespace': 'wrong-account'})
