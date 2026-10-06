from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.omni_channel.providers.base import installed_adapters


@tagged('post_install', '-at_install', 'omni_lifecycle')
class TestAdapterLifecycle(TransactionCase):
    def test_loaded_factory_follows_database_module_state(self):
        # Use a real installed module record; all changes roll back with the test.
        module = self.env['ir.module.module'].search([('name', '=', 'omni_channel')])
        provider = self.env['omni.channel.type'].create({'name': 'Lifecycle fixture', 'code': 'lifecycle_fixture'})
        purpose = self.env['omni.purpose'].create({'name': 'Lifecycle', 'code': 'lifecycle_fixture'})
        channel = self.env['omni.channel'].create({
            'name': 'Lifecycle fixture', 'purpose_id': purpose.id, 'channel_type_id': provider.id,
        })
        factory = object
        with patch.dict('odoo.addons.omni_channel.providers.base._ADAPTERS', {'lifecycle_fixture': factory}), \
                patch.dict('odoo.addons.omni_channel.providers.base._ADAPTER_MODULES', {'lifecycle_fixture': 'omni_channel'}):
            for state, available in [('installed', True), ('to upgrade', True), ('to remove', False), ('uninstalled', False), ('installed', True)]:
                with self.subTest(state=state):
                    module.state = state
                    provider.invalidate_recordset(['adapter_ready'])
                    channel.invalidate_recordset(['readiness'])
                    self.assertEqual(provider.adapter_ready, available)
                    self.assertEqual(channel.readiness, 'unconfigured' if available else 'unavailable')
                    self.assertIn('lifecycle_fixture', installed_adapters())
                    self.assertEqual('lifecycle_fixture' in installed_adapters(self.env), available)
            self.assertIs(installed_adapters()['lifecycle_fixture'], factory)

    def test_missing_addon_never_appears_ready(self):
        with patch.dict('odoo.addons.omni_channel.providers.base._ADAPTERS', {'missing_addon_fixture': object}), \
                patch.dict('odoo.addons.omni_channel.providers.base._ADAPTER_MODULES', {'missing_addon_fixture': 'does_not_exist'}):
            self.assertIn('missing_addon_fixture', installed_adapters())
            self.assertNotIn('missing_addon_fixture', installed_adapters(self.env))
