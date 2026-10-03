"""Database-free regression checks for shared navbar inheritance targets."""

import ast
from copy import deepcopy
from pathlib import Path
import unittest

from lxml import etree

from odoo.tools.template_inheritance import apply_inheritance_specs


class TestNavbarTemplates(unittest.TestCase):
    def test_home_and_branding_apps_menu_extensions_in_both_orders(self):
        addons = Path(__file__).resolve().parents[2]
        core = etree.parse(str(addons / 'web/static/src/webclient/navbar/navbar.xml'))
        home = etree.parse(str(addons / 'ai_home/static/src/navbar_home/navbar_home.xml'))
        branding = etree.parse(str(addons / 'branding/static/src/xml/apps_menu.xml'))
        base = core.xpath("//t[@t-name='web.NavBar.AppsMenu']")[0]
        self.assertFalse(home.xpath("//t[@t-inherit='web.NavBar.AppsMenu']"))
        manifest = ast.literal_eval((addons / 'ai_home/__manifest__.py').read_text())
        self.assertIn('views/ai_home_views.xml', manifest['data'])
        home_extension = etree.Element('t', {'t-name': 'ai_home.NativeAppsMenu'})
        branding_extension = branding.xpath("//t[@t-name='branding.ShadcnAppsMenu']")[0]

        for extensions in [(home_extension, branding_extension),
                           (branding_extension, home_extension)]:
            with self.subTest(order=[ext.get('t-name') for ext in extensions]):
                template = deepcopy(base)
                for extension in extensions:
                    specs = etree.Element('data')
                    for operation in extension.findall('xpath'):
                        specs.append(deepcopy(operation))
                    template = apply_inheritance_specs(template, specs)
                self.assertEqual(len(template.xpath(
                    "//Dropdown[not(@t-if)]//DropdownItem[@t-foreach='apps']"
                )), 1)
                self.assertEqual(len(template.xpath(
                    "//div[@class='o_navbar_apps_menu']/a[@t-on-click.prevent='this.openWorkDashboard']"
                )), 0)
                self.assertEqual(len(template.xpath(
                    "//div[@class='o_shadcn_app_item']"
                )), 1)


if __name__ == '__main__':
    unittest.main()
