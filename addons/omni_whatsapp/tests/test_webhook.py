"""Pure protocol checks: no Odoo database, tokens, email or network calls."""

import ast
import copy
import hashlib
import hmac
import importlib.util
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ADDON = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("omni_whatsapp_protocol_test", ADDON / "providers/webhook.py")
webhook = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = webhook
spec.loader.exec_module(webhook)

APP_SECRET = "synthetic_meta_app_secret"
VERIFY_TOKEN = "synthetic_separate_verify_token"
WABA = "123456789"
PHONE = "234567890"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


def fixture():
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA, "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": PHONE},
            "messages": [{"id": "wamid.synthetic-1", "from": "60123456789", "type": "text",
                          "timestamp": str(int(NOW.timestamp())), "text": {"body": "Hello 👋"}}],
        }}]}],
    }


def signed(raw, secret=APP_SECRET):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


def parse(value=None, **overrides):
    raw = json.dumps(value if value is not None else fixture(), ensure_ascii=False).encode()
    kwargs = dict(app_secret=APP_SECRET, business_account_id=WABA, phone_number_id=PHONE, now=NOW)
    kwargs.update(overrides)
    return webhook.text_messages(raw, signed(raw), **kwargs)


class TestWebhook(unittest.TestCase):
    def test_get_challenge_requires_separate_verify_token(self):
        parameters = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1234"}
        self.assertEqual(webhook.verification_challenge(parameters, VERIFY_TOKEN), "1234")
        for changed in ({"hub.mode": "other"}, {"hub.verify_token": APP_SECRET}, {"hub.challenge": ""}):
            with self.subTest(changed=changed), self.assertRaisesRegex(webhook.WebhookRejected, "verification"):
                webhook.verification_challenge({**parameters, **changed}, VERIFY_TOKEN)
        with self.assertRaises(webhook.WebhookRejected):
            webhook.verification_challenge(parameters, "")

    def test_raw_bytes_authenticated_not_reserialized_json(self):
        raw = b'{"text": "hello"}'
        self.assertTrue(webhook.verify_signature(raw, signed(raw), APP_SECRET))
        self.assertFalse(webhook.verify_signature(b'{"text":"hello"}', signed(raw), APP_SECRET))
        self.assertFalse(webhook.verify_signature(raw, signed(raw, VERIFY_TOKEN), APP_SECRET))

    def test_signature_rejects_missing_malformed_and_duplicate_headers(self):
        raw = b"{}"
        invalid = [{}, {"X-Hub-Signature-256": "sha1=abc"}, {"X-Hub-Signature-256": None},
                   {**signed(raw), "x-hub-signature-256": signed(raw)["X-Hub-Signature-256"]}]
        for headers in invalid:
            with self.subTest(headers=headers):
                self.assertFalse(webhook.verify_signature(raw, headers, APP_SECRET))
        self.assertTrue(webhook.verify_signature(raw, {k.lower(): v for k, v in signed(raw).items()}, APP_SECRET))

    def test_signature_checked_before_json_parsing(self):
        with self.assertRaisesRegex(webhook.WebhookRejected, "signature"):
            webhook.text_messages(b"not JSON", {}, app_secret=APP_SECRET,
                                  business_account_id=WABA, phone_number_id=PHONE)

    def test_invalid_unicode_does_not_escape_protocol_errors(self):
        self.assertFalse(webhook.verify_signature(b"{}", signed(b"{}"), "\ud800"))
        parameters = {"hub.mode": "subscribe", "hub.verify_token": "\ud800", "hub.challenge": "1234"}
        with self.assertRaisesRegex(webhook.WebhookRejected, "verification"):
            webhook.verification_challenge(parameters, VERIFY_TOKEN)
        value = fixture()
        value["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "\ud800"
        raw = json.dumps(value).encode()
        with self.assertRaisesRegex(webhook.WebhookRejected, "body"):
            webhook.text_messages(raw, signed(raw), app_secret=APP_SECRET,
                                  business_account_id=WABA, phone_number_id=PHONE, now=NOW)

    def test_text_identity_unicode_and_timestamp_preserved(self):
        message, = parse()
        self.assertEqual(message.business_account_id, WABA)
        self.assertEqual(message.phone_number_id, PHONE)
        self.assertEqual(message.sender_id, "60123456789")
        self.assertEqual(message.message_id, "wamid.synthetic-1")
        self.assertEqual(message.body, "Hello 👋")
        self.assertEqual(message.occurred_at, "2026-10-11 00:00:00")

    def test_wrong_business_account_or_phone_is_rejected(self):
        for changes in ({"business_account_id": "999"}, {"phone_number_id": "999"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(webhook.WebhookRejected, "scope"):
                parse(**changes)

    def test_batch_with_foreign_account_rejects_whole_batch(self):
        value = fixture()
        foreign = copy.deepcopy(value["entry"][0])
        foreign["id"] = "999"
        value["entry"].append(foreign)
        with self.assertRaisesRegex(webhook.WebhookRejected, "scope"):
            parse(value)

    def test_status_only_and_media_do_not_become_text(self):
        value = fixture()
        data = value["entry"][0]["changes"][0]["value"]
        data["messages"][0]["type"] = "image"
        self.assertEqual(parse(value), ())
        del data["messages"]
        data["statuses"] = [{"id": "wamid.synthetic-1", "status": "delivered"}]
        self.assertEqual(parse(value), ())

    def test_multiple_text_messages_preserved(self):
        value = fixture()
        messages = value["entry"][0]["changes"][0]["value"]["messages"]
        messages.append({**messages[0], "id": "wamid.synthetic-2"})
        self.assertEqual([m.message_id for m in parse(value)], ["wamid.synthetic-1", "wamid.synthetic-2"])

    def test_duplicate_message_ids_rejected(self):
        value = fixture()
        messages = value["entry"][0]["changes"][0]["value"]["messages"]
        messages.append(copy.deepcopy(messages[0]))
        with self.assertRaisesRegex(webhook.WebhookRejected, "duplicate"):
            parse(value)

    def test_invalid_message_and_future_timestamp_rejected(self):
        for field, bad in (("from", "not-an-id"), ("timestamp", str(int(NOW.timestamp()) + 301)),
                           ("timestamp", "-1"), ("timestamp", "0"), ("id", ""), ("text", {"body": " "})):
            value = fixture()
            value["entry"][0]["changes"][0]["value"]["messages"][0][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(webhook.WebhookRejected):
                parse(value)

    def test_malformed_signed_payload_errors_do_not_echo_secrets(self):
        for raw in (b"not JSON", b"[]", b'{"object":"a","object":"b"}'):
            with self.subTest(raw=raw), self.assertRaises(webhook.WebhookRejected) as caught:
                webhook.text_messages(raw, signed(raw), app_secret=APP_SECRET,
                                      business_account_id=WABA, phone_number_id=PHONE)
            self.assertNotIn(APP_SECRET, str(caught.exception))
            self.assertNotIn(raw.decode(), str(caught.exception))

    def test_body_and_batch_limits(self):
        raw = b"x" * (webhook.MAX_BODY + 1)
        self.assertFalse(webhook.verify_signature(raw, signed(raw), APP_SECRET))
        value = fixture()
        message = value["entry"][0]["changes"][0]["value"]["messages"][0]
        value["entry"][0]["changes"][0]["value"]["messages"] = [
            {**message, "id": f"wamid.{i}"} for i in range(webhook.MAX_MESSAGES + 1)
        ]
        with self.assertRaisesRegex(webhook.WebhookRejected, "size"):
            parse(value)

    def test_deep_structure_rejected(self):
        value = fixture()
        nested = value
        for _ in range(20):
            nested["extra"] = {}
            nested = nested["extra"]
        with self.assertRaisesRegex(webhook.WebhookRejected, "structure"):
            parse(value)

    def test_group_content_is_not_normalized_as_private_text(self):
        for location in ('value', 'message', 'context'):
            value = fixture()
            data = value['entry'][0]['changes'][0]['value']
            target = data if location == 'value' else data['messages'][0]
            if location == 'context':
                target['context'] = {}
                target = target['context']
            target['group_id'] = 'synthetic-group'
            with self.subTest(location=location):
                self.assertEqual(parse(value), ())

    def test_inbound_adapter_does_not_enable_outbound_dispatch(self):
        init = (ADDON / "providers/__init__.py").read_text()
        self.assertIn("module='omni_whatsapp'", init)
        adapter = ast.parse((ADDON / 'providers/adapter.py').read_text())
        cls = next(node for node in adapter.body if isinstance(node, ast.ClassDef))
        dispatch = next(node for node in cls.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'dispatch_supported' for t in node.targets))
        self.assertIs(dispatch.value.value, False)
        manifest = ast.literal_eval((ADDON / "__manifest__.py").read_text())
        self.assertEqual(manifest["depends"], ["omni_channel"])
        self.assertEqual(manifest["data"], ["views/credentials.xml"])
        self.assertFalse(manifest["auto_install"])


if __name__ == "__main__":
    unittest.main()
