import copy
import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.omni_channel.providers.dispatch import DispatchClaim
from odoo.addons.omni_telegram.providers.secrets import (
    TelegramConfigurationError,
    resolve,
)
from odoo.addons.omni_telegram.providers.telegram import TelegramAdapter
from odoo.addons.omni_telegram.providers.transport import (
    HTTPResult,
    TelegramHTTP,
    TelegramTransportError,
    public_address,
)

BOT = "987654321"
TOKEN = BOT + ":" + "synthetic_token_not_a_real_secret_1234"
SECRET = "synthetic_webhook_secret_for_tests_only"
REFERENCE = "OMNI_SECRET_TELEGRAM_TEST"


def fixture():
    return json.loads(
        (Path(__file__).parent / "fixtures/private_text.json").read_text(),
    )


def configuration(database="test", company=1):
    return {
        "account_key": BOT,
        "namespace": BOT,
        "sender_key": BOT,
        "credential_reference": REFERENCE,
        "adapter": {
            "database": database,
            "company_id": company,
            "sandbox_authorized": True,
            "sandbox_recipients": ["12345"],
        },
    }


def environment(config):
    return {
        REFERENCE: json.dumps(
            {
                "database": config["adapter"]["database"],
                "company_id": config["adapter"]["company_id"],
                "bot_id": BOT,
                "token": TOKEN,
                "webhook_secret": SECRET,
            },
        ),
    }


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.send_result = None

    def call(self, token, method, payload, **kwargs):
        assert token == TOKEN
        self.calls.append((method, payload))
        if method == "getMe":
            return HTTPResult(
                200, {"ok": True, "result": {"id": int(BOT), "is_bot": True}},
            )
        if method == "getChat":
            return HTTPResult(
                200,
                {
                    "ok": True,
                    "result": {"id": int(payload["chat_id"]), "type": "private"},
                },
            )
        assert method == "sendMessage"
        if isinstance(self.send_result, Exception):
            raise self.send_result
        return self.send_result or HTTPResult(
            200,
            {
                "ok": True,
                "result": {
                    "message_id": 43,
                    "chat": {"id": int(payload["chat_id"]), "type": "private"},
                    "from": {"id": int(BOT), "is_bot": True},
                    "text": payload["text"],
                },
            },
        )


@tagged("post_install", "-at_install")
class TestTelegramProvider(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = configuration()
        self.http = FakeHTTP()
        self.adapter = TelegramAdapter(
            self.http,
            lambda ref, config: resolve(ref, config, environment(self.config)),
        )
        payload = {
            "operation": "message.send",
            "recipient": "12345",
            "body": "We can help.",
            "account": BOT,
            "sender": BOT,
            "conversation": {
                "namespace": BOT,
                "endpoint": BOT,
                "thread": "12345",
                "identity": "12345",
            },
        }
        self.claim = DispatchClaim(
            1,
            1,
            "claim",
            "uuid",
            "telegram",
            json.dumps(payload),
            BOT,
            BOT,
            BOT,
            REFERENCE,
            json.dumps(self.config["adapter"]),
        )

    def test_scoped_secrets_reject_cross_database_company_bot_and_redact(self):
        secret = resolve(REFERENCE, self.config, environment(self.config))
        self.assertNotIn(TOKEN, repr(secret))
        for field, value in [("database", "other"), ("company_id", 2)]:
            config = copy.deepcopy(self.config)
            config["adapter"][field] = value
            with self.assertRaises(TelegramConfigurationError) as error:
                resolve(REFERENCE, config, environment(self.config))
            self.assertNotIn(TOKEN, str(error.exception))
        for ref in ["PATH", "/tmp/token", "OMNI_SECRET_" + "A" * 101]:
            with self.assertRaises(TelegramConfigurationError):
                resolve(ref, self.config, environment(self.config))
        config = dict(self.config, account_key="123")
        with self.assertRaises(TelegramConfigurationError):
            resolve(REFERENCE, config, environment(self.config))

    def test_verification_requires_authorized_account_and_exact_header(self):
        self.assertTrue(
            self.adapter.verify_request(
                b"{}", {"x-telegram-bot-api-secret-token": SECRET}, self.config,
            ),
        )
        for headers in [
            {},
            {"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            {
                "x-telegram-bot-api-secret-token": SECRET,
                "X-Telegram-Bot-Api-Secret-Token": SECRET,
            },
        ]:
            self.assertFalse(self.adapter.verify_request(b"{}", headers, self.config))
        self.config["adapter"]["sandbox_authorized"] = False
        self.assertFalse(
            self.adapter.verify_request(
                b"{}", {"x-telegram-bot-api-secret-token": SECRET}, self.config,
            ),
        )
        self.assertFalse(self.http.calls)

    def test_private_text_and_edit_have_stable_scope_and_revision(self):
        update = fixture()
        (event,) = self.adapter.normalize(update, self.config)
        self.assertEqual(
            (event.namespace, event.thread_key, event.message_key, event.revision),
            (BOT, "12345", "42", 0),
        )
        update["edited_message"] = update.pop("message")
        update["edited_message"]["edit_date"] = update["edited_message"]["date"] + 1
        (event,) = self.adapter.normalize(update, self.config)
        self.assertEqual(event.kind, "edit")
        self.assertGreater(event.revision, 0)

    def test_groups_media_business_bots_and_unlisted_recipients_are_ignored(self):
        variants = []
        for field, value in [
            ("photo", []),
            ("business_connection_id", "business"),
            ("message_thread_id", 1),
        ]:
            update = fixture()
            update["message"][field] = value
            variants.append(update)
        for field, value in [
            ("chat", {"id": -1, "type": "group"}),
            ("from", {"id": 12345, "is_bot": True}),
            ("chat", {"id": 999, "type": "private"}),
        ]:
            update = fixture()
            update["message"][field] = value
            variants.append(update)
        variants.append({"update_id": 2, "callback_query": {"data": "private"}})
        for update in variants:
            (event,) = self.adapter.normalize(update, self.config)
            self.assertEqual(event.kind, "unsupported")
            self.assertFalse(event.body)
        with self.assertRaises(TelegramConfigurationError):
            self.adapter.normalize({"update_id": True}, self.config)

    def test_preflight_and_accepted_result_are_bound_to_bot_and_private_chat(self):
        self.assertTrue(self.adapter.check_sender_health(self.config).healthy)
        self.assertTrue(
            self.adapter.validate_command(
                json.loads(self.claim.payload_json), self.config,
            ),
        )
        result = self.adapter.dispatch(self.claim)
        self.assertEqual(result.outcome, "accepted")
        self.assertEqual(result.provider_message_key, BOT + ":12345:43")
        self.assertEqual(
            [call[0] for call in self.http.calls], ["getMe", "getChat", "sendMessage"],
        )
        self.assertEqual(
            self.http.calls[-1][1]["link_preview_options"], {"is_disabled": True},
        )

    def test_timeout_server_errors_redirects_and_malformed_success_never_retry(self):
        for response in [
            TimeoutError(TOKEN),
            HTTPResult(500, {"ok": False, "error_code": 500}),
            HTTPResult(302, {}),
            HTTPResult(200, {"ok": True, "result": {}}),
            HTTPResult(200, []),
        ]:
            self.http.send_result = response
            before = len(self.http.calls)
            result = self.adapter.dispatch(self.claim)
            self.assertEqual(result.outcome, "unknown")
            self.assertFalse(result.retryable)
            self.assertEqual(len(self.http.calls), before + 1)
            self.assertNotIn(TOKEN, repr(result))

    def test_explicit_rejections_and_bounded_retry_after(self):
        for status in [400, 401, 403, 429]:
            self.http.send_result = HTTPResult(
                status,
                {"ok": False, "error_code": status, "parameters": {"retry_after": 7}},
            )
            result = self.adapter.dispatch(self.claim)
            self.assertEqual(result.outcome, "definitely_not_sent")
            self.assertEqual(result.retryable, status == 429)
        for delay in [True, -1, 86401, "7"]:
            self.http.send_result = HTTPResult(
                429,
                {"ok": False, "error_code": 429, "parameters": {"retry_after": delay}},
            )
            self.assertEqual(self.adapter.dispatch(self.claim).outcome, "unknown")

    def test_unapproved_or_unbound_payload_never_invokes_send(self):
        payload = json.loads(self.claim.payload_json)
        for changes in [
            {"recipient": "999"},
            {"body": "x" * 4097},
            {"conversation": {}},
            {"sender": "999"},
            {"body": "\x00"},
        ]:
            claim = replace(
                self.claim, payload_json=json.dumps(dict(payload, **changes)),
            )
            self.assertEqual(
                self.adapter.dispatch(claim).outcome, "definitely_not_sent",
            )
        self.assertFalse(self.http.calls)

    def test_network_default_off_and_dns_private_addresses_rejected(self):
        with (
            patch.dict(os.environ, {"OMNI_TELEGRAM_SANDBOX_NETWORK": "0"}),
            patch(
                "odoo.addons.omni_telegram.providers.transport.public_address",
            ) as lookup,
        ):
            with self.assertRaises(TelegramTransportError):
                TelegramHTTP().call(TOKEN, "getMe", {})
            lookup.assert_not_called()
        with patch(
            "socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaises(TelegramTransportError):
                public_address()

    def test_transport_uses_fixed_path_deadline_and_closes_resources(self):
        target = "odoo.addons.omni_telegram.providers.transport."
        connection, response = MagicMock(), MagicMock()
        response.status = 200
        response.read1.side_effect = [b'{"ok":true}', b""]
        with (
            patch.dict(os.environ, {"OMNI_TELEGRAM_SANDBOX_NETWORK": "1"}),
            patch(
                target + "public_address", return_value=(2, ("149.154.167.220", 443)),
            ),
            patch(target + "PinnedHTTPSConnection", return_value=connection),
            patch(target + "http.client.HTTPResponse", return_value=response),
            patch(target + "threading.Timer") as timer,
        ):
            self.assertEqual(TelegramHTTP().call(TOKEN, "getMe", {}).data, {"ok": True})
            self.assertLessEqual(timer.call_args.args[0], 25)
            timer.return_value.start.assert_called_once()
            timer.return_value.cancel.assert_called_once()
        self.assertEqual(
            connection.request.call_args.args[:2], ("POST", "/bot" + TOKEN + "/getMe"),
        )
        response.begin.assert_called_once()
        response.close.assert_called_once()
        connection.close.assert_called_once()
