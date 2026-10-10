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
        self.assertEqual(len(stages), 5)
        self.assertTrue(stages[1].xpath('.//field[@name="setup_bot_token"][@password="True"]'))
        self.assertTrue(stages[1].xpath('.//button[@name="action_setup_verify_bot"]'))
        for name in ('setup_bot_token', 'setup_webhook_secret'):
            field = stages[1].xpath('.//field[@name="%s"]' % name)[0]
            self.assertIn("setup_connection_mode != 'new'", field.getparent().get('invisible'))
        self.assertTrue(stages[2].xpath('.//field[@name="setup_callback_preview"]'))
        advanced = stages[2].xpath('.//div[@name="setup_receiving_settings"]')[0]
        self.assertFalse(stages[2].xpath('.//details'))
        self.assertIsNone(advanced.get('invisible'))
        self.assertIsNone(advanced.xpath('.//button[@name="action_setup_verify_webhook"]')[0].get('invisible'))
        self.assertFalse(advanced.xpath('.//field[@name="setup_callback_url"]'))
        self.assertTrue(stages[2].xpath('.//field[@name="setup_callback_preview"]'))
        self.assertTrue(stages[2].xpath('.//button[@name="action_setup_verify_webhook"]'))
        self.assertTrue(stages[2].xpath('.//button[@name="action_setup_connect_telegram"][@confirm]'))
        self.assertFalse(stages[2].xpath('.//button[@name="action_setup_webhook_secret"]'))
        self.assertFalse(stages[2].xpath('.//field[@name="setup_test_recipients"]'))
        self.assertTrue(stages[4].xpath('.//field[@name="setup_test_recipients"]'))
        self.assertFalse(advanced.xpath('.//field[@name="setup_test_recipients"]'))
        self.assertTrue(advanced.xpath('.//button[@name="action_setup_verify_webhook"]'))
        for name in ('setup_payload_days', 'setup_message_days', 'setup_blocked_days'):
            self.assertTrue(advanced.xpath('.//field[@name="%s"]' % name))
        self.assertFalse(form.xpath('.//field[@name="setup_authorization_evidence"]'))
        self.assertFalse(advanced.xpath('.//field[@name="setup_endpoint_health"]'))
        self.assertFalse(form.xpath('.//button[@name="action_setup_check_connection"]'))
        self.assertFalse(advanced.xpath('.//button[@name="action_setup_enable_receiving"]'))
        self.assertFalse(stages[2].xpath('.//button[@name="action_setup_open_bot"]'))
        self.assertFalse(stages[4].xpath('.//button[@name="action_setup_open_bot"]'))
        self.assertEqual(stages[2].xpath('.//div[@name="setup_receiving_actions"]')[0].get('invisible'), 'is_telegram')
        self.assertFalse(form.xpath('.//button[@name="action_setup_authorize_bot"]'))

        for name in ('action_setup_connect_telegram', 'action_setup_enable_receiving', 'action_setup_send_test'):
            self.assertTrue(form.xpath('.//button[@name="%s"][@confirm]' % name))
        self.assertEqual([b.get('name') for b in stages[4].xpath('.//button')], ['action_setup_send_test'])
        for field in ('approval_type_id', 'setup_conversation_id', 'setup_test_body', 'readiness', 'connection_status', 'attention'):
            self.assertFalse(stages[4].xpath('.//field[@name="%s"]' % field))
        self.assertTrue(stages[4].xpath('.//field[@name="setup_test_recipients"]'))
        self.assertNotIn('Manage connections', ''.join(form.itertext()))

    def test_compact_overview_hides_legacy_sections_and_keeps_dialogs_small(self):
        addons = Path(__file__).resolve().parents[2]
        base = etree.parse(str(addons / 'omni_channel/views/omni_views.xml'))
        dispatch = etree.parse(str(addons / 'omni_channel/views/dispatch_views.xml'))
        telegram = etree.parse(str(addons / 'omni_telegram/views/telegram_views.xml'))
        form = copy.deepcopy(base.xpath('//record[@id="channel_form"]//form')[0])
        for root, xmlid in ((dispatch, 'channel_dispatch_form'), (telegram, 'channel_telegram_form'),
                            (telegram, 'channel_telegram_overview_form')):
            specs = copy.deepcopy(root.xpath('//record[@id="%s"]/field[@name="arch"]' % xmlid)[0])
            specs.tag = 'data'
            form = apply_inheritance_specs(form, specs)
        sheet = form.find('sheet')
        for node in list(sheet)[:-1]:
            self.assertIn('is_telegram', node.get('invisible', ''))
        overview = sheet[-1]
        self.assertEqual(overview.get('name'), 'telegram_channel_overview')
        self.assertEqual([b.get('string') for b in overview.xpath('.//button')],
                         ['Open inbox', 'Channel settings', 'Edit test users'])
        self.assertFalse(overview.xpath('.//notebook | .//list | .//details'))
        dialog = telegram.xpath('//record[@id="telegram_channel_details_form"]//form')[0]
        self.assertFalse(dialog.xpath('.//field[@password] | .//details'))
        self.assertTrue(dialog.xpath('.//button[@string="Save test users"][@confirm]'))
        for name in ('message_days', 'payload_days', 'blocked_days', 'test_user_ids'):
            self.assertTrue(dialog.xpath('.//field[@name="%s"]' % name))

    def test_completed_cards_and_rows_offer_compact_progress_and_actions(self):
        addons = Path(__file__).resolve().parents[2]
        base = etree.parse(str(addons / 'omni_channel/views/omni_views.xml'))
        telegram = etree.parse(str(addons / 'omni_telegram/views/telegram_views.xml'))
        for kind in ('kanban', 'list'):
            specs = copy.deepcopy(telegram.xpath('//record[@id="channel_telegram_%s"]/field[@name="arch"]' % kind)[0])
            specs.tag = 'data'
            form = apply_inheritance_specs(copy.deepcopy(base.xpath('//record[@id="channel_%s"]/%s[@name="arch"]/*' % (kind, 'field'))[0]), specs)
            self.assertFalse(form.xpath('.//field[@name="setup_progress_label"]'))
            self.assertTrue(form.xpath('.//field[@name="setup_completed_steps"][@widget="omni_setup_progress"]'))
            for action in ('action_telegram_settings', 'action_telegram_open_inbox', 'action_telegram_edit_test_users'):
                self.assertTrue(form.xpath('.//button[@name="%s"]' % action))
            users = form.xpath('.//field[@name="telegram_overview_test_users"]')[0]
            self.assertTrue(users.get('groups') or users.xpath('ancestor::*[@groups]'))
            if kind == 'kanban':
                card = form.xpath('.//div[@name="telegram_channel_card"]')[0]
                self.assertTrue(card.xpath('.//span[contains(@class,"text-bg-success")][text()="Connected"]'))
                # Kanban forwards field attributes as component props: an empty
                # t-else on a widget field generates invalid JavaScript.
                self.assertFalse(card.xpath('.//field[@t-else]'))
                self.assertFalse(card.xpath('.//field[@name="telegram_overview_receiving"]'))
                self.assertTrue(card.xpath('.//div[@class="text-end"]/div/field[@name="channel_type_id"][@widget="badge"]'))
                self.assertTrue(card.xpath('.//div[@class="text-end"]/div/field[@name="purpose_id"]'))
                self.assertFalse(card.xpath('.//*[contains(@class,"border-top")]'))
                self.assertEqual([b.get('string') for b in card.xpath('.//button')], ['Edit test users', 'Inbox', 'Settings'])
                self.assertIn('ms-auto', card.xpath('.//button[@string="Settings"]')[0].get('class'))
                self.assertTrue(card.xpath('.//t[@t-else]/field[@name="telegram_overview_status"]'))
            else:
                validator = etree.RelaxNG(etree.parse(str(addons.parent / 'odoo/addons/base/rng/list_view.rng')))
                self.assertTrue(validator.validate(form), str(validator.error_log))


if __name__ == '__main__':
    unittest.main()
