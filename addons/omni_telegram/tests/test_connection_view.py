"""Database-free checks for the Telegram credential-first form."""
import copy
from pathlib import Path
import unittest

from lxml import etree
from odoo.tools.template_inheritance import apply_inheritance_specs


class TestTelegramConnectionView(unittest.TestCase):
    def test_runtime_credentials_precede_readonly_identity(self):
        addons = Path(__file__).resolve().parents[2]
        base = etree.parse(str(addons / 'omni_channel/views/omni_views.xml'))
        view = etree.parse(str(addons / 'omni_telegram/views/telegram_views.xml'))
        specs = copy.deepcopy(view.xpath('//record[@id="account_telegram_form"]/field[@name="arch"]')[0])
        specs.tag = 'data'
        form = apply_inheritance_specs(copy.deepcopy(base.xpath('//record[@id="omni_account_form"]//form')[0]), specs)
        refs = form.xpath('.//field[@name="credential_reference"]')
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].get('invisible'), 'is_telegram')
        token = form.xpath('.//field[@name="telegram_bot_token"]')[0]
        self.assertEqual(token.get('password'), 'True')
        self.assertIn('not telegram_has_credentials', token.get('required'))
        fields = [field.get('name') for field in token.getparent().findall('field')]
        self.assertLess(fields.index('company_id'), fields.index('telegram_bot_token'))
        self.assertLess(fields.index('telegram_bot_token'), fields.index('external_account_key'))
        self.assertTrue(form.xpath('.//button[@name="action_verify_telegram_bot"]'))
        for field in ('external_account_key', 'namespace'):
            self.assertEqual(form.xpath('.//field[@name="%s"]' % field)[0].get('readonly'), 'is_telegram')
        self.assertIn('Verification does not enable delivery', ''.join(form.itertext()))

    def test_guided_setup_embeds_credentials_and_explicit_activation(self):
        addons = Path(__file__).resolve().parents[2]
        base = etree.parse(str(addons / 'omni_channel/views/omni_views.xml'))
        view = etree.parse(str(addons / 'omni_telegram/views/telegram_views.xml'))
        specs = copy.deepcopy(view.xpath('//record[@id="telegram_channel_setup_form"]/field[@name="arch"]')[0])
        specs.tag = 'data'
        form = apply_inheritance_specs(copy.deepcopy(base.xpath('//record[@id="channel_setup_form"]//form')[0]), specs)
        stages = form.xpath('.//div[contains(@class,"o_omni_setup_stage_")]')
        self.assertEqual(len(stages), 6)
        self.assertTrue(stages[1].xpath('.//field[@name="setup_bot_token"][@password="True"]'))
        self.assertTrue(stages[1].xpath('.//button[@name="action_setup_verify_bot"]'))
        for name in ('setup_bot_token', 'setup_webhook_secret'):
            field = stages[1].xpath('.//field[@name="%s"]' % name)[0]
            self.assertIn("setup_connection_mode != 'new'", field.getparent().get('invisible'))
        self.assertTrue(stages[2].xpath('.//field[@name="setup_callback_url"]'))
        advanced = stages[2].xpath('.//details[@name="setup_receiving_advanced"]')[0]
        self.assertIsNone(advanced.get('open'))
        self.assertFalse(advanced.xpath('.//field[@name="setup_callback_url"]'))
        self.assertTrue(stages[2].xpath('.//field[@name="setup_callback_url"][@widget="omni_callback_input"]'))
        self.assertTrue(stages[2].xpath('.//button[@name="action_setup_verify_webhook"]'))
        for name in ('setup_endpoint_health', 'setup_test_recipients', 'setup_authorization_evidence', 'setup_payload_days', 'setup_message_days', 'setup_blocked_days'):
            self.assertTrue(advanced.xpath('.//field[@name="%s"]' % name))
        self.assertFalse(advanced.xpath('.//button[@name="action_setup_enable_receiving"]'))
        self.assertTrue(stages[2].xpath('.//button[@name="action_setup_open_bot"]'))
        self.assertTrue(stages[2].xpath('.//button[@name="action_messages"]'))

        for name in ('action_setup_authorize_bot', 'action_setup_enable_receiving', 'action_setup_activate'):
            self.assertTrue(form.xpath('.//button[@name="%s"][@confirm]' % name))
        self.assertTrue(stages[5].xpath('.//button[@name="action_setup_prepare_test"]'))
        self.assertNotIn('Manage connections', ''.join(form.itertext()))


if __name__ == '__main__':
    unittest.main()
