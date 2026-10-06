from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import ChromeBrowser


@tagged('post_install', '-at_install')
class TestOmniUI(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='omni_ui', groups='omni_channel.group_omni_manager',
        )
        purpose = cls.env['omni.purpose'].create(
            {
                'name': 'Customer care',
                'code': 'ui_test',
                'user_ids': [fields.Command.link(cls.manager.id)],
            },
        )
        channel_type = cls.env.ref('omni_channel.channel_type_telegram')
        cls.channel = cls.env['omni.channel'].create(
            {
                'name': 'Customer care / Telegram',
                'purpose_id': purpose.id,
                'channel_type_id': channel_type.id,
            },
        )
        account = cls.env['omni.account'].create(
            {
                'name': 'Care bot',
                'purpose_id': purpose.id,
                'channel_type_id': channel_type.id,
                'namespace': 'care-bot',
                'external_account_key': 'care-bot',
            },
        )
        cls.env['omni.outbound.sender'].create(
            {
                'name': 'Care bot',
                'channel_id': cls.channel.id,
                'account_id': account.id,
                'external_key': 'care-bot',
            },
        )

    def test_channel_cards_and_radio_selection_render(self):
        original_console = ChromeBrowser._handle_console

        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value') in ('omni_channels', 'omni_selection'):
                browser.take_screenshot(prefix=args[0]['value'] + '_')
            return original_console(browser, type, args=args, **kwargs)

        with patch.object(ChromeBrowser, '_handle_console', capture):
            self.browser_js(
                '/odoo/action-omni_channel.action_channels',
                """
                (async () => {
                async function waitFor(selector) {
                    for (let i = 0; i < 100; i++) {
                        const el = document.querySelector(selector);
                        if (el) return el;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing UI element: ' + selector);
                }
                const card = await waitFor('.o_omni_channel_card');
                if (!card.textContent.includes('No sender selected')) throw new Error('Missing readiness explanation');
                console.log('omni_channels');
                await new Promise(resolve => setTimeout(resolve, 300));
                card.click();
                (await waitFor('button[name="action_select_sender"]')).click();
                await waitFor('.modal input[type="radio"]');
                const modal = document.querySelector('.modal');
                if (!modal.textContent.includes('Check & Activate')) throw new Error('Missing confirmation action');
                if (!modal.textContent.includes('Failed checks preserve')) throw new Error('Missing impact explanation');
                console.log('omni_selection');
                await new Promise(resolve => setTimeout(resolve, 300));
                console.log('test successful');
                })().catch(error => console.error(error));
            """,
                ready='odoo.isReady === true',
                login='omni_ui',
                timeout=60,
            )
