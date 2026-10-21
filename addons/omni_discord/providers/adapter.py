"""Discord bot: text intake through the signed relay, approved replies over REST.

Threads are Discord channels: ``dm:<id>`` for a direct message with the bot,
``ch:<id>`` for a server channel chosen in setup. In a server channel the
reply mentions the person it answers and may mention nobody else.
"""

import hashlib
import json

from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.dispatch import DispatchResult
from odoo.addons.omni_channel.providers.inbound import InboundEvent

from . import rest, vault
from .relay import messages

REPLY_LIMIT = 1900


def bundle(config):
    scope = config["adapter"]
    return vault.load(config["credential_reference"], database=scope["database"],
                      company_id=scope["company_id"], purpose_id=scope["purpose_id"], bot_id=config["account_key"])


def channel_of(thread):
    kind, _sep, channel = (thread or "").partition(":")
    if kind not in ("dm", "ch") or not rest.snowflake(channel):
        raise ValueError("thread")
    return kind, channel


class DiscordAdapter:
    inbound_release_ready = True
    dispatch_supported = True

    def __init__(self, call=None):
        self.call = call or rest.call

    def check_sender_health(self, config):
        try:
            me = self.call(bundle(config)["bot_token"], "/users/@me")
            bot_id = me.get("id")
            good = (me.get("bot") is True and bot_id == config["account_key"] == config["namespace"]
                    and config.get("sender_key", bot_id) == bot_id)
            return HealthResult(True, bot_id, bot_id, bot_id) if good else HealthResult(False)
        except Exception:  # noqa: BLE001
            return HealthResult(False)

    def check_endpoint(self, config):
        credentials = bundle(config)
        return bool(credentials.get("relay_secret") and config["endpoint_key"] == config["account_key"]
                    and config["namespace"] == config["account_key"])

    def verify_request(self, raw, headers, config):
        credentials = bundle(config)
        self.messages = messages(raw, headers, secret=credentials.get("relay_secret") or "",
                                 bot_id=config["account_key"],
                                 allowed_channels=set(config["adapter"].get("channels") or ()))
        self.raw_hash = hashlib.sha256(raw).hexdigest()
        return True

    def normalize(self, value, config):
        return tuple(
            InboundEvent(event_key=m.message_id, endpoint_key=config["endpoint_key"], namespace=config["namespace"],
                         kind="message", sender_key=m.author_id, thread_key=m.thread, message_key=m.message_id,
                         body=m.body, occurred_at=m.occurred_at)
            for m in self.messages
        ) or (InboundEvent(event_key="unsupported:" + self.raw_hash, endpoint_key=config["endpoint_key"],
                           namespace=config["namespace"], kind="unsupported"),)

    def _payload_valid(self, payload, config):
        bot_id = config["account_key"]
        if not isinstance(payload, dict) or payload.get("operation") != "message.send":
            return False
        recipient, body, conversation = payload.get("recipient"), payload.get("body"), payload.get("conversation")
        if not (rest.snowflake(recipient) and recipient != bot_id and isinstance(body, str) and body.strip()
                and len(body) <= REPLY_LIMIT and "\x00" not in body and isinstance(conversation, dict)):
            return False
        try:
            kind, channel = channel_of(conversation.get("thread"))
        except ValueError:
            return False
        if kind == "ch" and channel not in set(config["adapter"].get("channels") or ()):
            return False
        return (payload.get("account") == bot_id and payload.get("sender") == bot_id
                and conversation.get("namespace") == bot_id and conversation.get("endpoint") == bot_id
                and conversation.get("identity") == recipient)

    def validate_command(self, payload, config):
        try:
            if not self._payload_valid(payload, config):
                return False
            kind, channel = channel_of(payload["conversation"]["thread"])
            found = self.call(bundle(config)["bot_token"], "/channels/" + channel)
            if kind == "dm":
                people = {u.get("id") for u in found.get("recipients") or []}
                return found.get("type") == 1 and payload["recipient"] in people
            return found.get("id") == channel and found.get("type") in (0, 5, 11, 12)
        except Exception:  # noqa: BLE001
            return False

    def dispatch(self, claim):
        config = {"account_key": claim.account_key, "namespace": claim.namespace, "sender_key": claim.sender_key,
                  "credential_reference": claim.credential_reference,
                  "adapter": json.loads(claim.adapter_config_json)}
        try:
            payload = json.loads(claim.payload_json)
            if not self._payload_valid(payload, config):
                return DispatchResult("definitely_not_sent", reason_code="invalid_recipient")
            kind, channel = channel_of(payload["conversation"]["thread"])
            token = bundle(config)["bot_token"]
        except Exception:  # noqa: BLE001 - nothing was sent yet
            return DispatchResult("definitely_not_sent", reason_code="unauthorized")
        content = payload["body"] if kind == "dm" else "<@%s> %s" % (payload["recipient"], payload["body"])
        try:
            result = self.call(token, "/channels/%s/messages" % channel, method="POST", body={
                "content": content,
                "allowed_mentions": {"parse": [], "users": [payload["recipient"]] if kind == "ch" else []},
            })
        except rest.RestError as error:
            if error.sent:
                return DispatchResult("unknown", reason_code="transport")
            if error.code == "rate_limited":
                delay = min(max(float(error.retry_after or 5), 1), 86400)
                return DispatchResult("definitely_not_sent", retryable=True, retry_after=delay, reason_code="rate_limited")
            if error.code == "unauthorized":
                return DispatchResult("definitely_not_sent", reason_code="unauthorized")
            return DispatchResult("definitely_not_sent", reason_code="invalid_recipient")
        except Exception:  # noqa: BLE001
            return DispatchResult("unknown", reason_code="transport")
        if rest.snowflake(result.get("id")) and result.get("channel_id") == channel \
                and (result.get("author") or {}).get("id") == claim.sender_key:
            return DispatchResult("accepted", provider_message_key=channel + ":" + result["id"])
        return DispatchResult("unknown", reason_code="invalid_result")
