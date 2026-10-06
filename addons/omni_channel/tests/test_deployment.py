from odoo.tests import TransactionCase, tagged

from odoo.addons.omni_channel.models.deployment import channel_origin


@tagged('post_install', '-at_install', 'omni_deployment')
class TestOmniDeployment(TransactionCase):
    def test_backend_hostname_derivation(self):
        for base, expected in [
            ('https://example.com', 'https://channels.example.com'),
            ('http://EXAMPLE.COM:8069/odoo', 'https://channels.example.com'),
            ('https://channels.example.com', 'https://channels.example.com'),
            ('https://example.co.uk', 'https://channels.example.co.uk'),
            ('https://tenant.example.com', 'https://channels.tenant.example.com'),
        ]:
            with self.subTest(base=base):
                self.assertEqual(channel_origin(base), expected)

    def test_no_public_domain_no_webhook(self):
        for base in [False, '', 'http://localhost:8069', 'http://127.0.0.1',
                     'http://[::1]:8069', 'https://192.0.2.10', 'http://odoo.internal',
                     'http://odoo.localhost', 'https://user:password@example.com',
                     'example.com', 'ftp://example.com', 'https://bad_host.example.com',
                     'https://exam\nple.com', 'http://[broken']:
            with self.subTest(base=base):
                self.assertFalse(channel_origin(base))

    def _endpoint(self, provider):
        purpose = self.env['omni.purpose'].create({'name': 'Deployment test', 'code': 'deployment_' + provider})
        channel_type = self.env.ref('omni_channel.channel_type_' + provider)
        channel = self.env['omni.channel'].create({
            'name': 'Deployment channel', 'purpose_id': purpose.id, 'channel_type_id': channel_type.id,
        })
        account = self.env['omni.account'].create({
            'name': 'Deployment bot', 'purpose_id': purpose.id, 'channel_type_id': channel_type.id,
            'namespace': 'deployment-bot', 'external_account_key': 'deployment-bot',
        })
        return self.env['omni.inbound.endpoint'].create({
            'name': 'Deployment endpoint', 'channel_id': channel.id,
            'account_id': account.id, 'external_key': 'deployment-bot',
        })

    def test_shared_rule_for_every_catalog_provider(self):
        self.env['ir.config_parameter'].sudo().set_str('web.base.url', 'https://example.com')
        for provider in self.env['omni.channel.type'].search([]).mapped('code'):
            with self.subTest(provider=provider):
                endpoint = self._endpoint(provider)
                self.assertEqual(
                    endpoint._get_webhook_url(),
                    f'https://channels.example.com/omni/inbound/{endpoint.route_key}',
                )

    def test_endpoint_uses_backend_changes_without_settings(self):
        endpoint = self._endpoint('telegram')
        before = endpoint.read(['state', 'route_key'])
        params = self.env['ir.config_parameter'].sudo()
        for base, origin in [('https://example.com', 'https://channels.example.com'),
                             ('https://new.example.org', 'https://channels.new.example.org')]:
            params.set_str('web.base.url', base)
            self.assertEqual(endpoint._get_webhook_url(), f'{origin}/omni/inbound/{endpoint.route_key}')
        params.set_str('web.base.url', 'http://localhost:8069')
        self.assertFalse(endpoint._get_webhook_url())
        self.assertEqual(endpoint.read(['state', 'route_key']), before)
        self.assertNotIn('omni_server_address', self.env['res.config.settings']._fields)
        self.assertFalse(self.env.ref('omni_channel.menu_deployment_settings', raise_if_not_found=False))
