"""Database-free checks for Owl 3 dashboard template bindings."""

from pathlib import Path
import re
import unittest

from lxml import etree


class TestDashboardTemplates(unittest.TestCase):
    def test_favorites_section_is_gone(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        self.assertFalse(template.xpath("//*[contains(@class, 'favorite')]"))
        self.assertFalse(template.xpath("//*[contains(@class, 'o_ai_home_mywork_more')]"),
                         'My Work sizes itself to the screen instead of a Show more button')

    def test_dashboard_icons_use_native_odoo20_markup(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        icons = template.xpath('//*[@data-icon]')
        self.assertEqual([icon.get('data-icon') for icon in icons], [
            'chevron_forward', 'arrow_upward', 'add', 'mic',
        ])
        self.assertFalse(template.xpath('//select[contains(@class, "o_ai_home_agent_select")]'),
                         'Agents are chosen from the picker')
        for icon in icons:
            self.assertIn('oi', icon.get('class').split())
            self.assertEqual(icon.get('aria-hidden'), 'true')
        self.assertFalse(template.xpath('//*[contains(@class, "fa-")]'))

    def test_home_columns_follow_the_layout_brief(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        main = template.xpath('//main[contains(@class, "o_ai_home_container")]')[0]
        columns = [child.get('class') for child in main]
        # The composer is its own grid item so the center column can scroll
        # underneath it without moving it.
        self.assertEqual(columns, ['o_ai_home_left', 'o_ai_home_center', 'o_ai_home_composer', 'o_ai_home_right'])
        self.assertTrue(template.xpath('//aside[@class="o_ai_home_left"]//section[contains(@class, "o_ai_home_mywork")]'))
        right = template.xpath('//aside[@class="o_ai_home_right"]/section/@class')
        self.assertEqual([cls.split()[-1] for cls in right],
                         ['o_ai_home_automations', 'o_ai_home_runs', 'o_ai_home_recent'])
        self.assertTrue(template.xpath('//div[contains(@class, "o_ai_home_status_filter")]'))
        # Titles stay outside the scrolling item lists.
        for section in template.xpath('//aside[@class="o_ai_home_right"]/section'):
            heading = section.xpath('div[contains(@class, "o_ai_home_section_heading")]')
            scroller = section.xpath('div[contains(@class, "o_ai_home_scroll")]')
            self.assertTrue(heading and scroller)
        self.assertTrue(template.xpath(
            '//section[contains(@class, "o_ai_home_mywork")]/div[contains(@class, "o_ai_home_scroll")]'))

    def test_attention_badge_uses_bundled_shield_image(self):
        module = Path(__file__).resolve().parents[1]
        template = etree.parse(str(module / 'static/src/dashboard/dashboard.xml'))
        icons = template.xpath('//img[@class="o_ai_home_attention_icon"]')
        self.assertEqual(len(icons), 1)
        self.assertEqual(icons[0].get('src'), '/ai_home/static/img/shield-logo.svg')
        self.assertEqual(icons[0].get('alt'), '')
        self.assertEqual(icons[0].get('aria-hidden'), 'true')
        asset = module / icons[0].get('src').removeprefix('/ai_home/')
        self.assertEqual(asset.read_text().splitlines()[0], (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            'role="img" aria-label="Green shield logo">'
        ))

    def test_component_members_use_owl3_context(self):
        source = Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.js'
        members = set(re.findall(r'\bget (\w+)\(', source.read_text()))
        members.update({'state', 'myWorkRef', 'fileInputRef'})
        template = etree.parse(str(source.with_suffix('.xml')))
        checked = 0
        for element in template.iter():
            for attribute, expression in element.attrib.items():
                if not attribute.startswith('t-'):
                    continue
                for member in members:
                    with self.subTest(attribute=attribute, expression=expression):
                        self.assertIsNone(re.search(
                            rf'(?<![\w.]){member}\b', expression
                        ))
                checked += 1
        self.assertGreater(checked, 50)
        self.assertEqual(template.xpath('//*[@t-ref]/@t-ref'), ['this.myWorkRef', 'this.fileInputRef'])


if __name__ == '__main__':
    unittest.main()
