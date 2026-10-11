"""Side-effect-free Meta webhook protocol. No HTTP, ORM, logging or credentials storage."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MAX_BODY = 1024 * 1024
MAX_MESSAGES = 100


class WebhookRejected(ValueError):
    """Only fixed error codes cross the boundary; never include payloads or secrets."""


def _text(value, limit):
    if not isinstance(value, str) or not 0 < len(value) <= limit or "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _id(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,31}", value) is not None


def verification_challenge(parameters, verify_token):
    """Return Meta's GET challenge only after checking the configured verify token."""
    token = parameters.get("hub.verify_token")
    challenge = parameters.get("hub.challenge")
    if (
        parameters.get("hub.mode") != "subscribe"
        or not _text(verify_token, 256)
        or not _text(token, 256)
        or not _text(challenge, 256)
        or not hmac.compare_digest(token.encode("utf-8"), verify_token.encode("utf-8"))
    ):
        raise WebhookRejected("verification")
    return challenge


def verify_signature(raw, headers, app_secret):
    """The POST signature uses the Meta app secret, not the GET verify token."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY or not _text(app_secret, 256):
        return False
    signatures = [v for k, v in headers.items() if k.lower() == "x-hub-signature-256"]
    if len(signatures) != 1 or not isinstance(signatures[0], str):
        return False
    signature = signatures[0]
    if re.fullmatch(r"sha256=[0-9a-f]{64}", signature) is None:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@dataclass(frozen=True)
class TextMessage:
    business_account_id: str
    phone_number_id: str
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


def text_messages(raw, headers, *, app_secret, business_account_id, phone_number_id, now=None):
    """Authenticate before decoding; bind each message to the configured WABA and number.

    Status-only notifications and non-text messages produce no text messages.
    This does not acknowledge, persist, deduplicate, process or send anything.
    """
    if not _id(business_account_id) or not _id(phone_number_id):
        raise WebhookRejected("scope")
    if not verify_signature(raw, headers, app_secret):
        raise WebhookRejected("signature")
    try:
        value = json.loads(raw, object_pairs_hook=_object)
        stack = [(value, 0)]
        count = 0
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > 16 or count > 10000:
                raise WebhookRejected("structure")
            if isinstance(node, dict):
                stack.extend((item, depth + 1) for item in node.values())
            elif isinstance(node, list):
                stack.extend((item, depth + 1) for item in node)
        if value.get("object") != "whatsapp_business_account" or not isinstance(value.get("entry"), list):
            raise WebhookRejected("schema")
        messages = []
        seen = set()
        upper = (now or datetime.now(UTC)) + timedelta(minutes=5)
        for entry in value["entry"]:
            if entry.get("id") != business_account_id:
                raise WebhookRejected("scope")
            if not isinstance(entry.get("changes"), list):
                raise WebhookRejected("schema")
            for change in entry["changes"]:
                if change.get("field") != "messages":
                    continue
                data = change["value"]
                if data.get("messaging_product") != "whatsapp":
                    raise WebhookRejected("schema")
                if data["metadata"].get("phone_number_id") != phone_number_id:
                    raise WebhookRejected("scope")
                if "group_id" in data or "group_id" in data["metadata"]:
                    continue  # Group intake is outside the private-text policy.
                items = data.get("messages", [])
                if not isinstance(items, list):
                    raise WebhookRejected("schema")
                for item in items:
                    if "group_id" in item or "group_id" in item.get("context", {}):
                        continue
                    if item.get("type") != "text":
                        continue
                    key, sender, body, stamp = item["id"], item["from"], item["text"]["body"], item["timestamp"]
                    if not _text(key, 256) or key != key.strip() or not _id(sender):
                        raise WebhookRejected("identity")
                    if not _text(body, 65536) or not body.strip():
                        raise WebhookRejected("body")
                    if not isinstance(stamp, str) or re.fullmatch(r"[0-9]{1,12}", stamp) is None:
                        raise WebhookRejected("timestamp")
                    occurred = datetime.fromtimestamp(int(stamp), UTC)
                    if occurred.year < 2000 or occurred > upper:
                        raise WebhookRejected("timestamp")
                    if key in seen:
                        raise WebhookRejected("duplicate")
                    seen.add(key)
                    messages.append(TextMessage(business_account_id, phone_number_id, key, sender, body,
                                                occurred.strftime("%Y-%m-%d %H:%M:%S")))
                    if len(messages) > MAX_MESSAGES:
                        raise WebhookRejected("size")
        return tuple(messages)
    except WebhookRejected:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, OSError):
        raise WebhookRejected("schema") from None
