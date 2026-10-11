"""Read-only Graph integration with fake HTTP; never contact Meta."""
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import requests

spec = importlib.util.spec_from_file_location("omni_whatsapp_connection_test", Path(__file__).resolve().parents[1] / "providers/connection.py")
connection = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = connection
spec.loader.exec_module(connection)

TOKEN = "synthetic_meta_token"
WABA = "123456789"


def phone(identifier="234567890"):
    return {"id": identifier, "verified_name": "Example team", "display_phone_number": "+60 12 345 6789"}


def http(status=200, content=None):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = status
    response.iter_content.return_value = [content if content is not None else json.dumps({"data": [phone()]}).encode()]
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    client = connection.GraphReadOnly("v99.0", session_factory=lambda: session)
    return client, session, response


class TestConnection(unittest.TestCase):
    def test_elapsed_workflow_never_reaches_network(self):
        client, session, _ = http()
        client.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(connection.ConnectionRejected, "network"):
            client.phone_numbers(WABA, TOKEN)
        session.get.assert_not_called()

    def test_slow_get_cannot_hold_caller_past_deadline(self):
        client, session, _ = http()
        def slow(*args, **kwargs):
            time.sleep(0.1)
            raise requests.Timeout()
        session.get.side_effect = slow
        client.deadline = time.monotonic() + 0.01
        started = time.monotonic()
        with self.assertRaisesRegex(connection.ConnectionRejected, "network"):
            client.phone_numbers(WABA, TOKEN)
        self.assertLess(time.monotonic() - started, 0.08)

    def test_get_is_fixed_host_read_only_and_token_not_in_url(self):
        client, session, response = http()
        self.assertEqual(client.phone_numbers(WABA, TOKEN)["data"][0]["id"], "234567890")
        session.get.assert_called_once()
        url = session.get.call_args.args[0]
        kwargs = session.get.call_args.kwargs
        self.assertTrue(url.startswith("https://graph.facebook.com/v99.0/123456789/phone_numbers?"))
        self.assertNotIn(TOKEN, url)
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer " + TOKEN})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["timeout"], (5, 10))
        self.assertFalse(session.trust_env)
        response.__exit__.assert_called_once()
        session.__exit__.assert_called_once()
        session.post.assert_not_called()

    def test_untrusted_account_and_credentials_never_reach_network(self):
        client, session, _ = http()
        for account, token in (("../me", TOKEN), ("001", TOKEN), (WABA, ""), (WABA, "bad\r\ntoken"), (WABA, "☃")):
            with self.subTest(account=account), self.assertRaises(connection.ConnectionRejected):
                client.phone_numbers(account, token)
        session.get.assert_not_called()

    def test_version_requires_explicit_valid_configuration(self):
        for version in ("", None, "latest", "v26.0/../me", "https://other.test"):
            with self.subTest(version=version), self.assertRaisesRegex(connection.ConnectionRejected, "version"):
                connection.GraphReadOnly(version)

    def test_provider_failures_are_sanitized_without_retries(self):
        for status, code in ((301, "provider"), (401, "credentials"), (403, "credentials"), (429, "rate_limited"), (500, "provider")):
            client, session, response = http(status, TOKEN.encode())
            with self.subTest(status=status), self.assertRaisesRegex(connection.ConnectionRejected, "^" + code + "$"):
                client.phone_numbers(WABA, TOKEN)
            session.get.assert_called_once()
            response.iter_content.assert_not_called()

    def test_timeout_is_sanitized_and_not_retried(self):
        client, session, _ = http()
        session.get.side_effect = requests.Timeout(TOKEN)
        with self.assertRaisesRegex(connection.ConnectionRejected, "^network$"):
            client.phone_numbers(WABA, TOKEN)
        session.get.assert_called_once()

    def test_bounded_response_and_invalid_json(self):
        for content, code in ((b"x" * (connection.MAX_RESPONSE + 1), "size"), (b"not-json", "response")):
            client, _, _ = http(content=content)
            with self.subTest(code=code), self.assertRaisesRegex(connection.ConnectionRejected, "^" + code + "$"):
                client.phone_numbers(WABA, TOKEN)

    def test_one_number_is_selected_automatically(self):
        transport = MagicMock()
        transport.phone_numbers.return_value = {"data": [phone()]}
        numbers = connection.verify_account(transport, WABA, TOKEN)
        selected = connection.select_phone(numbers)
        self.assertEqual(selected.id, "234567890")
        transport.phone_numbers.assert_called_once_with(WABA, TOKEN, None)

    def test_multiple_numbers_require_selection_and_reject_foreign_id(self):
        transport = MagicMock()
        transport.phone_numbers.return_value = {"data": [phone(), phone("345678901")]}
        numbers = connection.verify_account(transport, WABA, TOKEN)
        with self.assertRaisesRegex(connection.ConnectionRejected, "choose_number"):
            connection.select_phone(numbers)
        self.assertEqual(connection.select_phone(numbers, "345678901").id, "345678901")
        with self.assertRaisesRegex(connection.ConnectionRejected, "number_scope"):
            connection.select_phone(numbers, "999")

    def test_pagination_uses_cursor_and_never_remote_next_url(self):
        transport = MagicMock()
        transport.phone_numbers.side_effect = [
            {"data": [phone()], "paging": {"next": "https://evil.test/?access_token=" + TOKEN, "cursors": {"after": "next cursor"}}},
            {"data": [phone("345678901")]},
        ]
        self.assertEqual(len(connection.verify_account(transport, WABA, TOKEN)), 2)
        self.assertEqual(transport.phone_numbers.call_args.args, (WABA, TOKEN, "next cursor"))
        client, session, _ = http()
        client.phone_numbers(WABA, TOKEN, "abc&access_token=other")
        self.assertIn("after=abc%26access_token%3Dother", session.get.call_args.args[0])

    def test_empty_duplicate_or_malformed_phone_results_are_rejected(self):
        for result, code in (({"data": []}, "no_numbers"), ({"data": [phone(), phone()]}, "response"),
                             ({"data": [{**phone(), "id": "not-an-id"}]}, "response"),
                             ({"data": [{**phone(), "verified_name": ""}]}, "response"),
                             ({"data": [{**phone(), "verified_name": "\ud800"}]}, "response"),
                             ({"data": "invalid"}, "response"), ({"error": TOKEN}, "response")):
            transport = MagicMock()
            transport.phone_numbers.return_value = result
            with self.subTest(result=result), self.assertRaisesRegex(connection.ConnectionRejected, "^" + code + "$"):
                connection.verify_account(transport, WABA, TOKEN)

    def test_repeating_pagination_is_rejected(self):
        transport = MagicMock()
        transport.phone_numbers.side_effect = [
            {"data": [phone()], "paging": {"next": "anything", "cursors": {"after": "same"}}},
            {"data": [phone("345678901")], "paging": {"next": "anything", "cursors": {"after": "same"}}},
        ]
        with self.assertRaisesRegex(connection.ConnectionRejected, "^paging$"):
            connection.verify_account(transport, WABA, TOKEN)

    def test_page_budget_rejects_partial_number_lists(self):
        transport = MagicMock()
        transport.phone_numbers.side_effect = [
            {"data": [phone(str(i + 1))], "paging": {"next": "anything", "cursors": {"after": str(i)}}}
            for i in range(connection.MAX_PAGES)
        ]
        with self.assertRaisesRegex(connection.ConnectionRejected, "paging_limit"):
            connection.verify_account(transport, WABA, TOKEN)
        self.assertEqual(transport.phone_numbers.call_count, connection.MAX_PAGES)
