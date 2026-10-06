import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser

from .test_provider import SECRET, fixture
from .test_sandbox import TestTelegramSandbox


@tagged('post_install', '-at_install')
class TestTelegramHTTP(HttpCase, TestTelegramSandbox):
    def test_authenticated_telegram_webhook_is_durable_and_idempotent(self):
        self._activate()
        url = '/omni/inbound/' + self.endpoint.route_key
        raw = json.dumps(fixture()).encode()
        headers = {'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': SECRET}
        self.assertEqual(self.url_open(url, data=raw, headers={'Content-Type': 'application/json'}).status_code, 403)
        self.assertEqual(self.url_open(url, data=raw, headers=headers).status_code, 200)
        self.assertEqual(self.url_open(url, data=raw, headers=headers).status_code, 200)
        self.assertEqual(self.env['omni.webhook.event'].search_count([('endpoint_id', '=', self.endpoint.id)]), 1)
        self.assertFalse(any(method == 'sendMessage' for method, _ in self.http.calls))

    def test_native_account_requires_explicit_confirmation(self):
        original = ChromeBrowser._handle_console

        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value') == 'telegram_sandbox':
                browser.take_screenshot(prefix='telegram_sandbox_')
            return original(browser, type, args=args, **kwargs)

        with patch.object(ChromeBrowser, '_handle_console', capture):
            self.browser_js(
                f'/odoo/action-omni_channel.action_omni_account/{self.account.id}',
                """
                (async () => {
                    async function waitFor(selector) {
                        for (let i=0; i<100; i++) {
                            const element = document.querySelector(selector);
                            if (element) return element;
                            await new Promise(resolve => setTimeout(resolve, 100));
                        }
                        throw new Error('Missing element: ' + selector);
                    }
                    const button = await waitFor('button[name="action_authorize_telegram_sandbox"]');
                    if (!document.body.textContent.includes('Private text only.')) throw new Error('Missing scope explanation');
                    if (document.querySelector('button[name="action_revoke_telegram_sandbox"]')) throw new Error('Unapproved account offers revoke');
                    button.click();
                    await waitFor('.modal');
                    if (!document.querySelector('.modal').textContent.includes('Each reply still requires')) throw new Error('Missing approval explanation');
                    console.log('telegram_sandbox');
                    await new Promise(resolve => setTimeout(resolve, 400));
                    console.log('test successful');
                })().catch(error => console.error(error));
                """, ready='odoo.isReady === true', login='omni_manager', timeout=60,
            )
        self.assertFalse(self.account.telegram_sandbox_authorized)
        self.assertFalse(self.http.calls)
