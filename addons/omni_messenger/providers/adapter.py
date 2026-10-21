"""Messenger for one Facebook Page: receive private text, send approved replies.

Replies use the standard messaging window: Meta accepts a ``RESPONSE`` message
only within 24 hours of the person's last message to the Page. The window is
checked against Meta's own conversation record before each send.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.dispatch import DispatchResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent

from . import graph, vault
from .webhook import text_messages

WINDOW = timedelta(hours=24)
REPLY_LIMIT = 2000


def bundle(config):
    scope = config["adapter"]
    return vault.load(config["credential_reference"], database=scope["database"],
                      company_id=scope["company_id"], purpose_id=scope["purpose_id"],
                      page_id=config["account_key"])


def _stamp(value):
    try:
        return datetime.fromisoformat(value.replace("+0000", "+00:00")).astimezone(UTC)
    except (AttributeError, TypeError, ValueError):
        return None


class MessengerAdapter:
    inbound_release_ready = True
    dispatch_supported = True

    def __init__(self, call=None):
        self.call = call or graph.call

    # ---- health -------------------------------------------------------------

    def check_sender_health(self, config):
        try:
            token = bundle(config)["access_token"]
            value = self.call(token, "/me", params={"fields": "id,name,category"})
            page_id = value.get("id")
            good = (
                graph.identifier(page_id) and value.get("category")
                and page_id == config["account_key"] == config["namespace"]
                and config.get("sender_key", page_id) == page_id
            )
            return HealthResult(bool(good), page_id, page_id, page_id) if good else HealthResult(False)
        except Exception:  # noqa: BLE001 - never surface provider errors or secrets
            return HealthResult(False)

    def check_endpoint(self, config):
        credentials = bundle(config)
        return bool(config.get("messenger_callback_verified") and credentials.get("app_secret")
                    and credentials.get("verify_token") and config["endpoint_key"] == config["account_key"]
                    and config["namespace"] == config["account_key"])

    # ---- intake -------------------------------------------------------------

    def verify_request(self, raw, headers, config):
        credentials = bundle(config)
        self.messages = text_messages(raw, headers, app_secret=credentials["app_secret"],
                                      page_id=config["account_key"])
        self.raw_hash = hashlib.sha256(raw).hexdigest()
        return True

    def normalize(self, value, config):
        return tuple(
            InboundEvent(event_key=m.message_id, endpoint_key=config["endpoint_key"], namespace=config["namespace"],
                         kind="message", sender_key=m.sender_id, thread_key=m.sender_id, message_key=m.message_id,
                         body=m.body, occurred_at=m.occurred_at)
            for m in self.messages
        ) or (InboundEvent(event_key="unsupported:" + self.raw_hash, endpoint_key=config["endpoint_key"],
                           namespace=config["namespace"], kind="unsupported"),)

    # ---- replies ------------------------------------------------------------

    def _payload_valid(self, payload, page_id):
        if not isinstance(payload, dict) or payload.get("operation") != "message.send":
            return False
        recipient, body, conversation = payload.get("recipient"), payload.get("body"), payload.get("conversation")
        return bool(
            graph.identifier(recipient) and recipient != page_id
            and isinstance(body, str) and body.strip() and len(body) <= REPLY_LIMIT and "\x00" not in body
            and isinstance(conversation, dict)
            and payload.get("account") == page_id and payload.get("sender") == page_id
            and conversation.get("namespace") == page_id and conversation.get("endpoint") == page_id
            and conversation.get("thread") == recipient and conversation.get("identity") == recipient
        )

    def _within_window(self, token, page_id, recipient, now=None):
        """Meta's record of the person's last message to the Page, not our copy."""
        value = self.call(token, "/%s/conversations" % page_id, params={
            "platform": "messenger", "user_id": recipient,
            "fields": "messages.limit(10){from,created_time}",
        })
        threads = value.get("data")
        if not isinstance(threads, list) or len(threads) != 1:
            return False
        items = ((threads[0].get("messages") or {}).get("data")) or []
        latest = [
            _stamp(m.get("created_time")) for m in items
            if isinstance(m, dict) and (m.get("from") or {}).get("id") == recipient
        ]
        latest = [t for t in latest if t]
        return bool(latest) and max(latest) >= (now or datetime.now(UTC)) - WINDOW

    def validate_command(self, payload, config):
        try:
            page_id = config["account_key"]
            if not self._payload_valid(payload, page_id):
                return False
            token = bundle(config)["access_token"]
            return self._within_window(token, page_id, payload["recipient"])
        except Exception:  # noqa: BLE001 - read-only preflight
            return False

    def dispatch(self, claim):
        config = {"account_key": claim.account_key, "namespace": claim.namespace, "sender_key": claim.sender_key,
                  "credential_reference": claim.credential_reference,
                  "adapter": json.loads(claim.adapter_config_json)}
        page_id = claim.account_key
        try:
            payload = json.loads(claim.payload_json)
            if not self._payload_valid(payload, page_id):
                return DispatchResult("definitely_not_sent", reason_code="invalid_recipient")
            token = bundle(config)["access_token"]
        except Exception:  # noqa: BLE001 - nothing was sent yet
            return DispatchResult("definitely_not_sent", reason_code="unauthorized")
        try:
            result = self.call(token, "/%s/messages" % page_id, method="POST", body={
                "recipient": {"id": payload["recipient"]},
                "messaging_type": "RESPONSE",
                "message": {"text": payload["body"]},
            })
        except graph.GraphError as error:
            if error.sent:
                return DispatchResult("unknown", reason_code="transport")
            if error.code == "rate_limited":
                return DispatchResult("definitely_not_sent", retryable=True, retry_after=60, reason_code="rate_limited")
            if error.code == "unauthorized":
                return DispatchResult("definitely_not_sent", reason_code="unauthorized")
            return DispatchResult("definitely_not_sent", reason_code="invalid_recipient")
        except Exception:  # noqa: BLE001 - once invoked, never infer non-delivery
            return DispatchResult("unknown", reason_code="transport")
        mid = result.get("message_id")
        if result.get("recipient_id") == payload["recipient"] and isinstance(mid, str) and mid:
            return DispatchResult("accepted", provider_message_key=(page_id + ":" + mid)[:256])
        return DispatchResult("unknown", reason_code="invalid_result")
