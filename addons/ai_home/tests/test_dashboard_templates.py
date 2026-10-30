"""Database-free checks for the Home template (approved "Odoo home" design)."""

from pathlib import Path
import re
import unittest

from lxml import etree

MODULE = Path(__file__).resolve().parents[1]


def _template():
    return etree.parse(str(MODULE / 'static/src/dashboard/dashboard.xml'))


class TestDashboardTemplates(unittest.TestCase):
    def test_sections_follow_the_design(self):
        template = _template()
        root = template.xpath('//div[contains(@class, "o_ai_home ")]')[0]
        self.assertEqual([child.get('class') for child in root], ['o_ai_home_grid'], 'no greeting or top bar')
        grid = root[0]
        self.assertEqual([child.get('class') for child in grid], ['o_ai_home_panes', 'o_ai_home_ask'])
        panes = {pane.get('class').split()[-1]: [cls.split()[-1] for cls in pane.xpath('section/@class')]
                 for pane in grid[0]}
        self.assertEqual(panes, {
            'o_ai_home_center': ['o_ai_home_attention'],
            'o_ai_home_left': ['o_ai_home_today', 'o_ai_home_team', 'o_ai_home_plan', 'o_ai_home_waiting',
                               'o_ai_home_recent'],
            'o_ai_home_right': ['o_ai_home_feed'],
        })
        # Three columns down to the bottom of the page, the assistant under the middle one; nothing floats.
        scss = (MODULE / 'static/src/dashboard/dashboard.scss').read_text()
        self.assertIn('"left center right"', scss)
        self.assertIn('"left ask right"', scss)
        self.assertNotIn('position: fixed', scss)
        self.assertIn('--home-pad: 24px', scss)
        self.assertIn('--home-pad: 16px', scss)

    def test_live_figures_and_my_day_are_gone(self):
        text = etree.tostring(_template(), encoding='unicode')
        for gone in ('Right now', 'o_ai_home_live', 'o_ai_home_tile', 'o_ai_home_day', 'ai_home.LiveHint',
                     'Open all in Activities', 'See all activity'):
            self.assertNotIn(gone, text)

    def test_old_home_parts_are_gone(self):
        template = _template()
        for old in ('o_ai_home_mywork', 'o_ai_home_automations', 'o_ai_home_runs', 'o_ai_home_dictate',
                    'o_ai_home_mode_select', 'o_ai_home_prepare', 'o_ai_home_disclaimer', 'favorite',
                    'o_ai_home_global_search', 'o_ai_home_quick', 'o_ai_home_greeting', 'o_ai_home_top'):
            self.assertFalse(template.xpath(f'//*[contains(@class, "{old}")]'), old)

    def test_icons_use_native_odoo20_markup(self):
        icons = _template().xpath('//*[@data-icon]')
        self.assertEqual([icon.get('data-icon') for icon in icons], ['add', 'arrow_upward'])
        for icon in icons:
            self.assertIn('oi', icon.get('class').split())
            self.assertEqual(icon.get('aria-hidden'), 'true')
        self.assertFalse(_template().xpath('//*[contains(@class, "fa-")]'))

    def test_component_members_use_owl3_context(self):
        source = MODULE / 'static/src/dashboard/dashboard.js'
        members = set(re.findall(r'\bget (\w+)\(', source.read_text()))
        members.update({'state', 'fileInputRef', 'promptRef'})
        template = _template()
        checked = 0
        for element in template.iter():
            for attribute, expression in element.attrib.items():
                if not attribute.startswith('t-'):
                    continue
                for member in members:
                    with self.subTest(attribute=attribute, expression=expression):
                        self.assertIsNone(re.search(rf'(?<![\w.]){member}\b', expression))
                checked += 1
        self.assertGreater(checked, 50)
        self.assertEqual(template.xpath('//*[@t-ref]/@t-ref'), ['this.fileInputRef', 'this.promptRef'])

    def test_global_search_is_removed_from_the_navbar(self):
        self.assertFalse((MODULE / 'static/src/global_search').exists())


if __name__ == '__main__':
    unittest.main()
