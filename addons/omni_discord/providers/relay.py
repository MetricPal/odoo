"""Signed hand-off from the gateway relay to Odoo (no ORM, no HTTP).

The relay holds Discord's gateway connection and POSTs each new message to
the channel's inbound URL. Odoo accepts a batch only with a valid HMAC over
``<timestamp>.<body>`` made with the channel's relay secret, at most five
minutes old.
"""

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MAX_BODY = 512 * 1024
MAX_MESSAGES = 50
SKEW = 300
SIGNATURE = "X-Omni-Relay-Signature"
TIMESTAMP = "X-Omni-Relay-Timestamp"


class RelayRejected(ValueError):
    pass


def sign(secret, raw, timestamp=None):
    timestamp = str(int(timestamp if timestamp is not None else time.time()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {SIGNATURE: "sha256=" + digest, TIMESTAMP: timestamp, "Content-Type": "application/json"}


def _snowflake(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{14,21}", value) is not None


def _header(headers, name):
    found = [v for k, v in headers.items() if k.lower() == name.lower()]
    return found[0] if len(found) == 1 and isinstance(found[0], str) else None


@dataclass(frozen=True)
class RelayMessage:
    message_id: str
    channel_id: str
    guild_id: str
    author_id: str
    author_name: str
    body: str
    occurred_at: str

    @property
    def thread(self):
        return ("ch:" if self.guild_id else "dm:") + self.channel_id


def messages(raw, headers, *, secret, bot_id, allowed_channels, now=None):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY or not isinstance(secret, str) or len(secret) < 32:
        raise RelayRejected("size")
    signature, stamp = _header(headers, SIGNATURE), _header(headers, TIMESTAMP)
    if not signature or not stamp or not re.fullmatch(r"[0-9]{9,11}", stamp):
        raise RelayRejected("signature")
    current = now.timestamp() if now else time.time()
    if abs(current - int(stamp)) > SKEW:
        raise RelayRejected("timestamp")
    expected = sign(secret, raw, int(stamp))[SIGNATURE]
    if not hmac.compare_digest(signature, expected):
        raise RelayRejected("signature")
    try:
        value = json.loads(raw)
        events = value.get("messages")
        if value.get("bot_id") != bot_id or not isinstance(events, list) or len(events) > MAX_MESSAGES:
            raise RelayRejected("schema")
        upper = (now or datetime.now(UTC)) + timedelta(minutes=5)
        result, seen = [], set()
        for item in events:
            author = item.get("author") or {}
            if author.get("bot") or author.get("id") == bot_id:
                continue
            key, channel, guild = item.get("id"), item.get("channel_id"), item.get("guild_id") or ""
            body = item.get("content")
            if not (_snowflake(key) and _snowflake(channel) and _snowflake(author.get("id"))):
                raise RelayRejected("identity")
            if guild and (not _snowflake(guild) or channel not in allowed_channels):
                continue  # Only the server channels chosen in setup; DMs are always private to the bot.
            if not isinstance(body, str) or not body.strip() or len(body) > 4000 or "\x00" in body:
                continue  # Attachments, embeds and empty messages are not text intake.
            occurred = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).astimezone(UTC)
            if occurred.year < 2015 or occurred > upper:
                raise RelayRejected("timestamp")
            if key in seen:
                raise RelayRejected("duplicate")
            seen.add(key)
            result.append(RelayMessage(key, channel, guild, author["id"],
                                       str(author.get("global_name") or author.get("username") or "")[:100],
                                       body, occurred.strftime("%Y-%m-%d %H:%M:%S")))
        return tuple(result)
    except RelayRejected:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RelayRejected("schema") from None
