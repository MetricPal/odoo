"""Telegram Bot API: approved sandbox replies, private text only."""

import hmac
import json
from datetime import UTC, datetime

from .secrets import TelegramConfigurationError, canonical_id, resolve
from .transport import TelegramHTTP
from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.dispatch import DispatchResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent


class TelegramAdapter:
    dispatch_supported = True
    inbound_release_ready = (
        True  # Code capability, not permission: per-account checks below.
    )

    def __init__(self, transport=None, resolver=None):
        self.transport = transport if transport is not None else TelegramHTTP()
        self.resolver = resolver if resolver is not None else resolve

    def _sandbox(self, config, authorized=True):
        bot = canonical_id(config["account_key"])
        if (
            config["namespace"] != bot
            or config.get("sender_key", config.get("endpoint_key")) != bot
        ):
            raise TelegramConfigurationError()
        binding = config["adapter"]
        recipients = binding.get("sandbox_recipients")
        if (
            (authorized and binding.get("sandbox_authorized") is not True)
            or not isinstance(recipients, list)
            or not 1 <= len(recipients) <= 10
        ):
            raise TelegramConfigurationError()
        if any(canonical_id(key) != key for key in recipients) or len(
            set(recipients),
        ) != len(recipients):
            raise TelegramConfigurationError()
        return bot, recipients

    def check_sender_health(self, config):
        try:
            bot, _recipients = self._sandbox(config, authorized=False)
            secret = self.resolver(config["credential_reference"], config)
            result = self.transport.call(secret.token, "getMe", {}, verify_only=True)
            user = result.data.get("result") if isinstance(result.data, dict) else None
            good = (
                result.status == 200
                and result.data.get("ok") is True
                and isinstance(user, dict)
                and user.get("is_bot") is True
                and canonical_id(user.get("id")) == bot
            )
            return HealthResult(bool(good), bot, bot, bot)
        except Exception:  # noqa: BLE001 - sanitize all provider/secret failures
            return HealthResult(False)

    def check_endpoint(self, config):
        self._sandbox(config)
        return self.check_sender_health(config).healthy

    def verify_request(self, raw, headers, config):
        try:
            self._sandbox(config)
            secret = self.resolver(
                config["credential_reference"], config,
            ).webhook_secret
            values = [
                value
                for key, value in headers.items()
                if key.lower() == "x-telegram-bot-api-secret-token"
            ]
            return (
                len(values) == 1
                and isinstance(values[0], str)
                and len(values[0]) <= 256
                and hmac.compare_digest(values[0].encode(), secret.encode())
            )
        except Exception:  # noqa: BLE001
            return False

    def normalize(self, value, config):
        bot, recipients = self._sandbox(config)
        if (
            not isinstance(value, dict)
            or type(value.get("update_id")) is not int
            or not 0 <= value["update_id"] <= 2147483647
        ):
            raise TelegramConfigurationError()
        key = str(value["update_id"])
        ignored = (InboundEvent(key, bot, bot, "unsupported"),)
        kinds = [kind for kind in value if kind != "update_id"]
        if len(kinds) != 1 or kinds[0] not in ("message", "edited_message"):
            return ignored
        kind = kinds[0]
        message = value[kind]
        if not isinstance(message, dict):
            raise TelegramConfigurationError()
        # Business, guest, topics, paid/media/service messages are separate contracts.
        if any(
            key in message
            for key in (
                "business_connection_id",
                "guest_query_id",
                "message_thread_id",
                "photo",
                "video",
                "audio",
                "document",
                "animation",
                "sticker",
                "voice",
                "video_note",
                "contact",
                "location",
                "venue",
                "poll",
                "dice",
                "sender_chat",
                "via_bot",
                "is_topic_message",
                "paid_media",
                "rich_message",
            )
        ):
            return ignored
        chat, sender, body = (
            message.get("chat"),
            message.get("from"),
            message.get("text"),
        )
        if (
            not isinstance(chat, dict)
            or chat.get("type") != "private"
            or not isinstance(sender, dict)
            or sender.get("is_bot") is not False
        ):
            return ignored
        sender_key, thread_key = (
            canonical_id(sender.get("id")),
            canonical_id(chat.get("id")),
        )
        if (
            sender_key != thread_key
            or sender_key not in recipients
            or not isinstance(body, str)
            or not body.strip()
        ):
            return ignored
        message_key = canonical_id(message.get("message_id"))
        stamp = message.get("date")
        revision = message.get("edit_date", 0) if kind == "edited_message" else 0
        if (
            type(stamp) is not int
            or stamp <= 0
            or type(revision) is not int
            or not 0 <= revision <= 2147483647
        ):
            raise TelegramConfigurationError()
        if kind == "edited_message" and revision < stamp:
            raise TelegramConfigurationError()
        occurred = datetime.fromtimestamp(revision or stamp, UTC).strftime(
            "%Y-%m-%d %H:%M:%S",
        )
        return (
            InboundEvent(
                key,
                bot,
                bot,
                "edit" if revision else "message",
                sender_key,
                thread_key,
                message_key,
                body,
                occurred,
                revision,
            ),
        )

    def _payload_valid(self, payload, config):
        bot, recipients = self._sandbox(config)
        if not isinstance(payload, dict) or payload.get("operation") != "message.send":
            return False
        recipient, body, conversation = (
            payload.get("recipient"),
            payload.get("body"),
            payload.get("conversation"),
        )
        if (
            recipient not in recipients
            or not isinstance(body, str)
            or not body.strip()
            or len(body) > 4096
            or "\x00" in body
            or not isinstance(conversation, dict)
        ):
            return False
        body.encode("utf-8")
        return (
            payload.get("account") == bot
            and payload.get("sender") == bot
            and conversation.get("namespace") == bot
            and conversation.get("endpoint") == bot
            and conversation.get("thread") == recipient
            and conversation.get("identity") == recipient
        )

    def validate_command(self, payload, config):
        try:
            if not self._payload_valid(payload, config):
                return False
            secret = self.resolver(config["credential_reference"], config)
            result = self.transport.call(
                secret.token, "getChat", {"chat_id": payload["recipient"]},
            )
            chat = result.data.get("result") if isinstance(result.data, dict) else None
            return (
                result.status == 200
                and result.data.get("ok") is True
                and isinstance(chat, dict)
                and chat.get("type") == "private"
                and canonical_id(chat.get("id")) == payload["recipient"]
            )
        except Exception:  # noqa: BLE001
            return False

    def dispatch(self, claim):
        config = {
            "account_key": claim.account_key,
            "namespace": claim.namespace,
            "sender_key": claim.sender_key,
            "credential_reference": claim.credential_reference,
            "adapter": json.loads(claim.adapter_config_json),
        }
        try:
            payload = json.loads(claim.payload_json)
            if not self._payload_valid(payload, config):
                return DispatchResult(
                    "definitely_not_sent", reason_code="invalid_recipient",
                )
            secret = self.resolver(claim.credential_reference, config)
        except Exception:  # noqa: BLE001 - nothing was sent yet
            return DispatchResult("definitely_not_sent", reason_code="unauthorized")
        try:
            result = self.transport.call(
                secret.token,
                "sendMessage",
                {
                    "chat_id": payload["recipient"],
                    "text": payload["body"],
                    "link_preview_options": {"is_disabled": True},
                },
            )
            data = result.data
            if not isinstance(data, dict):
                return DispatchResult("unknown", reason_code="invalid_result")
            if result.status == 200 and data.get("ok") is True:
                message = data.get("result", {})
                chat, sender = message.get("chat", {}), message.get("from", {})
                if (
                    chat.get("type") == "private"
                    and canonical_id(chat.get("id")) == payload["recipient"]
                    and sender.get("is_bot") is True
                    and canonical_id(sender.get("id")) == claim.sender_key
                    and message.get("text") == payload["body"]
                ):
                    # Message IDs are scoped by chat/bot; retain an unambiguous key.
                    key = (
                        claim.sender_key
                        + ":"
                        + payload["recipient"]
                        + ":"
                        + canonical_id(message.get("message_id"))
                    )
                    return DispatchResult("accepted", provider_message_key=key)
            if data.get("ok") is False and data.get("error_code") == result.status:
                if result.status == 429:
                    delay = data.get("parameters", {}).get("retry_after")
                    if type(delay) is int and 1 <= delay <= 86400:
                        return DispatchResult(
                            "definitely_not_sent",
                            retryable=True,
                            retry_after=delay,
                            reason_code="rate_limited",
                        )
                if result.status in (401, 403):
                    return DispatchResult(
                        "definitely_not_sent", reason_code="unauthorized",
                    )
                if result.status == 400:
                    return DispatchResult(
                        "definitely_not_sent", reason_code="invalid_recipient",
                    )
            return DispatchResult("unknown", reason_code="invalid_result")
        except Exception:  # noqa: BLE001 - once invoked, never infer no acceptance
            return DispatchResult("unknown", reason_code="transport")
