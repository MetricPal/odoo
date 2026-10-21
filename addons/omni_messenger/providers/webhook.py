"""Side-effect-free Messenger webhook protocol: signature, handshake and text messages."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MAX_BODY = 1024 * 1024
MAX_MESSAGES = 100


class WebhookRejected(ValueError):
    """Fixed codes only; never payloads or secrets."""


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and "\x00" not in value


def _id(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,31}", value) is not None


def verification_challenge(parameters, verify_token):
    token = parameters.get("hub.verify_token")
    challenge = parameters.get("hub.challenge")
    if (
        parameters.get("hub.mode") != "subscribe"
        or not _text(verify_token, 256) or not _text(token, 256) or not _text(challenge, 256)
        or not hmac.compare_digest(token.encode(), verify_token.encode())
    ):
        raise WebhookRejected("verification")
    return challenge


def verify_signature(raw, headers, app_secret):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY or not _text(app_secret, 256):
        return False
    found = [v for k, v in headers.items() if k.lower() == "x-hub-signature-256"]
    if len(found) != 1 or not isinstance(found[0], str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", found[0]):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(found[0], expected)


@dataclass(frozen=True)
class TextMessage:
    message_id: str
    sender_id: str
    body: str
    occurred_at: str


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise WebhookRejected("structure")
        value[key] = item
    return value


def text_messages(raw, headers, *, app_secret, page_id, now=None):
    """Authenticate, then return private text messages sent to this Page.

    Echoes of the Page's own messages, attachments, reactions, reads and
    deliveries produce nothing. Nothing is stored or sent here.
    """
    if not _id(page_id):
        raise WebhookRejected("scope")
    if not verify_signature(raw, headers, app_secret):
        raise WebhookRejected("signature")
    try:
        value = json.loads(raw, object_pairs_hook=_object)
        if value.get("object") != "page" or not isinstance(value.get("entry"), list) or len(value["entry"]) > 100:
            raise WebhookRejected("schema")
        upper = (now or datetime.now(UTC)) + timedelta(minutes=5)
        messages, seen = [], set()
        for entry in value["entry"]:
            if entry.get("id") != page_id:
                raise WebhookRejected("scope")
            events = entry.get("messaging", [])
            if not isinstance(events, list):
                raise WebhookRejected("schema")
            for event in events:
                message = event.get("message")
                if not isinstance(message, dict) or message.get("is_echo") or "text" not in message:
                    continue
                sender = (event.get("sender") or {}).get("id")
                recipient = (event.get("recipient") or {}).get("id")
                key, body, stamp = message.get("mid"), message["text"], event.get("timestamp")
                if recipient != page_id or not _id(sender) or sender == page_id:
                    raise WebhookRejected("identity")
                if not _text(key, 256) or key != key.strip():
                    raise WebhookRejected("identity")
                if not _text(body, 65536) or not body.strip():
                    raise WebhookRejected("body")
                if type(stamp) is not int or not 0 < stamp < 10 ** 14:
                    raise WebhookRejected("timestamp")
                occurred = datetime.fromtimestamp(stamp / 1000, UTC)
                if occurred.year < 2000 or occurred > upper:
                    raise WebhookRejected("timestamp")
                if key in seen:
                    raise WebhookRejected("duplicate")
                seen.add(key)
                messages.append(TextMessage(key, sender, body, occurred.strftime("%Y-%m-%d %H:%M:%S")))
                if len(messages) > MAX_MESSAGES:
                    raise WebhookRejected("size")
        return tuple(messages)
    except WebhookRejected:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, OSError):
        raise WebhookRejected("schema") from None
