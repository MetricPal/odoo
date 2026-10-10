"""Database-free checks for the native channel overview view contract."""
from pathlib import Path
import unittest

from lxml import etree


class TestChannelViews(unittest.TestCase):
    def test_native_overview_team_panel_and_optional_columns(self):
        root = etree.parse(str(Path(__file__).resolve().parents[1] / 'views/omni_views.xml'))
        action = root.xpath('//record[@id="action_channels"]')[0]
        self.assertEqual(action.find("field[@name='view_mode']").text, 'kanban,list,form')
        self.assertEqual(action.find("field[@name='search_view_id']").get('ref'), 'channel_search')
        self.assertEqual(action.find("field[@name='limit']").text, '80')
        panel = root.xpath('//record[@id="channel_search"]//searchpanel')[0]
        self.assertEqual(panel.get('view_types'), 'kanban,list')
        self.assertEqual(panel.find('field').get('name'), 'purpose_id')
        self.assertEqual(panel.find('field').get('enable_counters'), '1')
        self.assertEqual([f.get('name') for f in panel.findall('field')], ['purpose_id', 'channel_type_id'])
        self.assertEqual(panel.findall('field')[1].get('string'), 'Channel types')
        self.assertEqual(panel.findall('field')[1].get('select'), 'one')
        kanban = root.xpath('//record[@id="channel_kanban"]//kanban')[0]
        self.assertEqual(kanban.get('records_draggable'), 'false')
        self.assertFalse(kanban.get('class'))
        self.assertEqual(kanban.get('can_open'), 'false')
        self.assertFalse(kanban.xpath('.//field[@name="sender_count"] | .//field[@name="endpoint_count"]'))
        self.assertNotIn('Runtime sender:', ''.join(kanban.itertext()))
        self.assertFalse(kanban.xpath('.//*[contains(@class,"border-top")]'))
        self.assertIsNone(root.xpath('//record[@id="channel_list"]//list')[0].get('no_open'))
        columns = root.xpath('//record[@id="channel_list"]//list/field')
        for column in columns:
            if column.get('name') not in {'name', 'purpose_id', 'channel_type_id', 'readiness', 'setup_progress_label', 'setup_step_total', 'setup_completed_steps'}:
                self.assertEqual(column.get('optional'), 'hide')

    def test_setup_uses_native_form_and_five_steps(self):
        module = Path(__file__).resolve().parents[1]
        root = etree.parse(str(module / 'views/omni_views.xml'))
        action = root.xpath('//record[@id="action_channel_setup"]')[0]
        self.assertEqual(action.find("field[@name='view_id']").get('ref'), 'channel_setup_form')
        form = root.xpath('//record[@id="channel_setup_form"]//form')[0]
        self.assertEqual(form.get('js_class'), 'omni_channel_setup')
        self.assertEqual(len(form.xpath('.//div[contains(@class,"o_omni_setup_stage_")]')), 5)
        self.assertFalse(form.xpath('.//field[@name="dispatch_enabled"]'))
        for field in ('name', 'purpose_id', 'channel_type_id', 'setup_account_id', 'setup_callback_url'):
            self.assertTrue(form.xpath('.//field[@name="%s"]' % field))
        self.assertFalse(form.xpath('.//button[@name="action_manage_connections"]'))
        self.assertNotIn('Manage connections', ''.join(form.itertext()))
        template = etree.parse(str(module / 'static/src/channel_setup/channel_setup.xml'))
        for css in ('o_search_panel', 'o_search_panel_resize', 'o_form_renderer', 'o_form_sheet_bg', 'o-mail-ChatterContainer'):
            self.assertTrue(template.xpath('//*[contains(@class,"%s")]' % css))

    def test_connection_help_lives_in_guidance_panel(self):
        module = Path(__file__).resolve().parents[1]
        root = etree.parse(str(module / 'views/omni_views.xml'))
        field = root.xpath('//record[@id="channel_setup_form"]//field[@name="setup_account_id"]')[0]
        self.assertEqual(field.get('string'), 'Connection')
        self.assertEqual(field.get('placeholder'), 'Select a saved connection')
        self.assertEqual(field.getparent().get('invisible'), "setup_connection_mode != 'existing'")
        self.assertTrue(root.xpath('//record[@id="channel_setup_form"]//field[@name="setup_connection_mode"][@widget="radio"]'))
        template = etree.parse(str(module / 'static/src/channel_setup/channel_setup.xml'))
        guide = template.xpath('//aside[@aria-label="Setup guidance"]')[0]
        for step in range(1, 5):
            self.assertTrue(guide.xpath('.//t[@t-if="this.setupState.step === %s"]' % step))
        text = ''.join(guide.itertext())
        for phrase in ('No records', 'Create new connection', 'Verify bot', 'Switching choices clears unsaved credentials'):
            self.assertIn(phrase, text)

    def test_progress_and_resume_on_both_views(self):
        root = etree.parse(str(Path(__file__).resolve().parents[1] / 'views/omni_views.xml'))
        for view in ('channel_kanban', 'channel_list'):
            node = root.xpath('//record[@id="%s"]' % view)[0]
            self.assertFalse(node.xpath('.//field[@name="setup_progress_label"]'))
            self.assertEqual(node.xpath('.//button[@name="action_open_channel"]')[0].get('invisible'), 'setup_completed_steps != 5')
            self.assertTrue(node.xpath('.//field[@name="setup_completed_steps"][@widget="omni_setup_progress"]'))
            buttons = node.xpath('.//button[@name="action_continue_setup"]')
            self.assertEqual([button.get('string') for button in buttons], ['Start setup', 'Continue setup'])
            self.assertEqual(buttons[0].get('invisible'), 'setup_completed_steps != 0')
            self.assertEqual(buttons[1].get('invisible'), 'setup_completed_steps == 0 or setup_completed_steps == 5')
            for button in buttons:
                self.assertEqual(button.get('groups'), 'omni_channel.group_omni_manager')
        filter_node = root.xpath('//record[@id="channel_search"]//filter[@name="setup_incomplete"]')[0]
        self.assertEqual(filter_node.get('domain'), "[('setup_completed_steps', '<', 5)]")

    def test_native_list_and_search_schema(self):
        module = Path(__file__).resolve().parents[1]
        schemas = module.parents[1] / 'odoo/addons/base/rng'
        root = etree.parse(str(module / 'views/omni_views.xml'))
        for tag in ('list', 'search'):
            validator = etree.RelaxNG(etree.parse(str(schemas / (tag + '_view.rng'))))
            for arch in root.xpath('//field[@name="arch"]/' + tag):
                self.assertTrue(validator.validate(arch), str(validator.error_log))

    def test_pending_receiving_offers_draft_path(self):
        module = Path(__file__).resolve().parents[1]
        root = etree.parse(str(module / 'static/src/channel_setup/channel_setup.xml'))
        self.assertEqual(root.xpath('//button[@t-on-click="this.deferReceiving"]')[0].text, 'Next: Branding')
        self.assertTrue(root.xpath('//button[@t-on-click="this.saveSetupDraft"]'))
        branch = root.xpath('//button[@t-on-click="this.deferReceiving"]/..')[0]
        self.assertIn('!this.model.root.data.setup_connection_ready', branch.get('t-if'))
        self.assertIn('!this.model.root.data.is_telegram', branch.get('t-if'))
        form = etree.parse(str(module / 'views/omni_views.xml'))
        for name in ('setup_completed_step_ids', 'setup_receiving_ready'):
            self.assertTrue(form.xpath('//record[@id="channel_setup_form"]//field[@name="%s"]' % name))


if __name__ == '__main__':
    unittest.main()
