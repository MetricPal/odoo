from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSocialWidgets(HttpCase):
    def test_credentials_widget(self):
        module_hash = 0
        for char in '@omni_social/credentials':
            module_hash = ((module_hash << 5) - module_hash + ord(char)) & 0xFFFFFFFF
        self.browser_js(
            f'/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id={module_hash:08x}',
            '', login='admin', timeout=180,
            success_signal='[HOOT] Test suite succeeded',
        )
