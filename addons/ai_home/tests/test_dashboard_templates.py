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
        self.assertEqual([child.get('class') for child in root], ['o_ai_home_top', 'o_ai_home_grid'])
        top = [child.get('class').split()[0] for child in root[0]]
        self.assertEqual(top, ['o_ai_home_greeting', 'o_ai_home_card', 'o_ai_home_live'])
        grid = root[1]
        self.assertEqual([child.get('class') for child in grid], ['o_ai_home_panes', 'o_ai_home_ask'])
        panes = {pane.get('class').split()[-1]: [cls.split()[-1] for cls in pane.xpath('section/@class')]
                 for pane in grid[0]}
        self.assertEqual(panes, {
            'o_ai_home_center': ['o_ai_home_attention'],
            'o_ai_home_left': ['o_ai_home_day', 'o_ai_home_recent'],
            'o_ai_home_right': ['o_ai_home_feed'],
        })
        # Three columns down to the bottom of the page, the assistant under the middle one; nothing floats.
        scss = (MODULE / 'static/src/dashboard/dashboard.scss').read_text()
        self.assertIn('"left center right"', scss)
        self.assertIn('"left ask right"', scss)
        self.assertNotIn('position: fixed', scss)
        self.assertIn('--home-pad: 24px', scss)
        self.assertIn('--home-pad: 16px', scss)

    def test_live_figures_use_a_hinted_indicator(self):
        template = _template()
        self.assertNotIn('Right now', etree.tostring(template, encoding='unicode'))
        dot = template.xpath('//span[@class="o_ai_home_live_dot"]')[0]
        self.assertEqual(dot.get('data-tooltip-template'), 'ai_home.LiveHint')
        self.assertTrue(dot.get('aria-label'))
        hint = template.xpath('//t[@t-name="ai_home.LiveHint"]')[0]
        dots = hint.xpath('.//i/@class')
        self.assertEqual(dots, ['o_ai_home_hint_dot o_tone_bad', 'o_ai_home_hint_dot o_tone_warn',
                                'o_ai_home_hint_dot o_tone_good'])

    def test_old_home_parts_are_gone(self):
        template = _template()
        for old in ('o_ai_home_mywork', 'o_ai_home_automations', 'o_ai_home_runs', 'o_ai_home_dictate',
                    'o_ai_home_mode_select', 'o_ai_home_prepare', 'o_ai_home_disclaimer', 'favorite',
                    'o_ai_home_global_search'):
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
