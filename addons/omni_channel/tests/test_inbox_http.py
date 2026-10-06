import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser

from .test_inbox import TestOmniInbox


@tagged("post_install", "-at_install")
class TestOmniInboxHTTP(HttpCase, TestOmniInbox):
    def _post(self, body=None, headers=None, suffix=""):
        return self.url_open(
            "/omni/inbound/" + self.endpoint.route_key + suffix,
            data=body
            if body is not None
            else json.dumps({"events": [self._data()]}).encode(),
            headers=headers
            if headers is not None
            else {"Content-Type": "application/json", "X-Test-Signature": "verified"},
        )

    def test_webhook_authentication_bounds_and_duplicates(self):
        self.assertEqual(
            self._post(headers={"Content-Type": "application/json"}).status_code, 403,
        )
        self.assertEqual(self._post(body=b"{").status_code, 400)
        self.assertEqual(self._post(body=b"x" * (1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self._post(suffix="?db=forged").status_code, 404)
        self.assertFalse(
            self.env["omni.webhook.event"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(
            self.env["omni.webhook.event"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
            1,
        )
        self.endpoint.with_user(self.manager).action_disable()
        self.assertEqual(self._post().status_code, 404)

    def test_persistence_failure_does_not_acknowledge_or_leave_partial_event(self):
        model = type(self.env["omni.webhook.event"])
        original = model._store

        def fail_after_store(records, *args):
            original(records, *args)
            message = "SECRET_MUST_NOT_APPEAR_IN_RESPONSE"
            raise RuntimeError(message)

        with patch.object(model, "_store", fail_after_store):
            response = self._post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET", response.text)
        self.assertFalse(
            self.env["omni.webhook.event"].search_count(
                [("endpoint_id", "=", self.endpoint.id)],
            ),
        )
        self.assertEqual(self._post().status_code, 200)

    def test_native_inbox_renders_untrusted_text_and_assignment(self):
        self._receive(body="<script>window.omniInjected=true</script> Please help.")
        conversation = self._process()
        original_console = ChromeBrowser._handle_console

        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get("value") == "omni_inbox":
                browser.take_screenshot(prefix="omni_inbox_")
            return original_console(browser, type, args=args, **kwargs)

        with patch.object(ChromeBrowser, "_handle_console", capture):
            self.browser_js(
                f"/odoo/action-omni_channel.action_inbox/{conversation.id}",
                """
                (async () => {
                    async function waitFor(selector) {
                        for (let i = 0; i < 100; i++) {
                            const el = document.querySelector(selector);
                            if (el) return el;
                            await new Promise(resolve => setTimeout(resolve, 100));
                        }
                        throw new Error('Missing inbox element: ' + selector);
                    }
                    const assign = await waitFor('button[name="action_assign_me"]');
                    if (!document.body.textContent.includes('Please help.')) throw new Error('Message not shown');
                    if (window.omniInjected) throw new Error('Untrusted message executed');
                    if (!document.body.textContent.includes('Select a healthy sender')) throw new Error('Missing reply hold reason');
                    if (document.querySelector('button[name="action_prepare_reply"]')) throw new Error('Unavailable reply action shown');
                    assign.click();
                    await new Promise(resolve => setTimeout(resolve, 600));
                    console.log('omni_inbox');
                    await new Promise(resolve => setTimeout(resolve, 400));
                    console.log('test successful');
                })().catch(error => console.error(error));
                """,
                ready="odoo.isReady === true",
                login="omni_operator",
                timeout=60,
            )
        conversation.invalidate_recordset()
        self.assertEqual(conversation.assigned_user_id, self.operator)
