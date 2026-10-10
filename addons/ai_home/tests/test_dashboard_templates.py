"""Database-free checks for Owl 3 dashboard template bindings."""

from pathlib import Path
import re
import unittest

from lxml import etree


class TestDashboardTemplates(unittest.TestCase):
    def test_favorite_star_is_only_available_when_favorites_are_expanded(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        buttons = template.xpath(
            "//button[contains(@class, 'o_ai_home_favorite_toggle') and @aria-pressed='true']"
        )
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('t-if'), 'app and this.state.showAllApps')
        self.assertEqual(len(buttons[0].xpath("span[@data-icon='star' and @class='oi oi-filled']")), 1)

    def test_available_app_stars_require_favorite_capacity(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        buttons = template.xpath("//button[@class='o_ai_home_favorite_toggle']")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('t-if'), 'this.hasFavoriteCapacity')

    def test_favorites_view_all_only_shows_when_apps_are_available(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        buttons = template.xpath("//button[contains(@class, 'o_ai_home_favorites_view_all')]")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('t-if'), 'this.nonFavoriteApps.length')

    def test_dashboard_icons_use_native_odoo20_markup(self):
        template = etree.parse(str(
            Path(__file__).resolve().parents[1] / 'static/src/dashboard/dashboard.xml'
        ))
        icons = template.xpath('//*[@data-icon]')
        self.assertEqual(len(icons), 5)
        self.assertEqual([icon.get('data-icon') for icon in icons], [
            'chevron_forward', 'chevron_forward', 'star', 'star',
            'chevron_forward',
        ])
        for icon in icons:
            self.assertIn('oi', icon.get('class').split())
            self.assertEqual(icon.get('aria-hidden'), 'true')
        self.assertFalse(template.xpath('//*[contains(@class, "fa-")]'))
        available_star = template.xpath('//span[@data-icon="star" and @t-att-class]')[0]
        self.assertIn("'oi-filled': this.isFavorite(app)", available_star.get('t-att-class'))

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
        members.update({'state', 'favoritesRootRef', 'getAppInitial', 'isFavorite'})
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
        self.assertEqual(template.xpath('//*[@t-ref]/@t-ref'), ['this.favoritesRootRef'])


if __name__ == '__main__':
    unittest.main()
