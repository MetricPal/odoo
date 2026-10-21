from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from .test_users import new_test_user

from .test_foundation import HealthyAdapter, TestOmniFoundation


@tagged('post_install', '-at_install')
class TestOmniAdministration(TestOmniFoundation):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='omni_technical_admin', groups='base.group_system')

    def test_administrator_app_navigation(self):
        # Decision 2026-10-21: administrators get an Omnichannel launcher instead of
        # Settings > Technical (developer mode only). Staff do not see it.
        root = self.env.ref('omni_channel.menu_omni_technical')
        self.assertFalse(root.parent_id)
        self.assertEqual(root.web_icon, 'omni_channel,static/description/icon.svg')
        self.assertEqual(root.child_id.sorted('sequence').mapped('name'),
                         ['Channels', 'Outgoing messages', 'Receiving rules', 'Blocklist'])
        self.assertIn(root, self.env['ir.ui.menu'].with_user(self.admin).get_user_roots())
        for user in (self.manager, self.operator):
            self.assertNotIn(root, self.env['ir.ui.menu'].with_user(user).get_user_roots())
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

    def test_channel_type_connector_filter_accepts_odoo20_operators(self):
        Type = self.env['omni.channel.type']
        ready = Type.search([('adapter_ready', 'in', [True])])
        self.assertEqual(Type.web_search_read([('adapter_ready', '=', True)], {'name': {}})['length'], len(ready))
        self.assertEqual(ready | Type.search([('adapter_ready', 'not in', [True])]), Type.search([]))

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


@tagged('post_install', '-at_install')
class TestSetupBindingValues(TestOmniFoundation):
    def test_retention_fields_follow_and_write_the_policy(self):
        # These were related fields through non-searchable computes (registry warnings);
        # they are plain computes now and must still read and write the policy.
        policy = self.env['omni.inbound.policy'].create({'name': 'Rules', 'channel_id': self.channel.id,
                                                         'payload_days': 3, 'message_days': 30, 'blocked_days': 10})
        channel = self.channel.with_user(self.manager)
        self.assertEqual(channel.setup_policy_id, policy)
        self.assertEqual(channel.setup_message_days, policy.message_days)
        self.assertEqual(channel.setup_policy_state, policy.state)
        channel.setup_message_days = 40
        self.assertEqual(policy.message_days, 40)
        policy.write({'payload_days': 4})
        self.assertEqual(channel.setup_payload_days, 4)
        channel.write({'setup_payload_days': 5, 'setup_message_days': 60, 'setup_blocked_days': 20})
        self.assertEqual((policy.payload_days, policy.message_days, policy.blocked_days), (5, 60, 20))

    def test_no_unsearchable_dependency_warnings(self):
        import warnings
        registry = self.env.registry
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            for name, model in registry.items():
                if name.startswith(('omni.', 'social.')):
                    for field in model._fields.values():
                        list(field.resolve_depends(registry))
        self.assertFalse([str(w.message) for w in caught if 'omni.' in str(w.message) and 'searchable' in str(w.message)])
