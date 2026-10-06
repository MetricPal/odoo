"""Bounded, verified adapter input. No ORM or external side effects here."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .base import get_adapter

MAX_BODY = 1024 * 1024
MAX_EVENTS = 100


class IngressRejected(Exception):
    """Safe protocol rejection; never include provider errors or payloads."""


def reject(code):
    raise IngressRejected(code)


@dataclass(frozen=True)
class InboundEvent:
    event_key: str
    endpoint_key: str
    namespace: str
    kind: str
    sender_key: str = ""
    thread_key: str = ""
    message_key: str = ""
    body: str = ""
    occurred_at: str = ""
    revision: int = 0
    private: bool = True


def verified_events(provider, raw, headers, config):
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY:
        reject("size")
    try:
        adapter = get_adapter(provider)
        if not getattr(adapter, "inbound_release_ready", False):
            reject("unavailable")
        # Original bytes, before decoding or transformations; adapters do not log them.
        if adapter.verify_request(raw, headers, config) is not True:
            reject("verification")
        value = json.loads(raw)
        stack = [(value, 0)]
        nodes = 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > 16 or nodes > 10000:
                reject("structure")
            if isinstance(item, dict):
                stack.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                stack.extend((v, depth + 1) for v in item)
        events = adapter.normalize(value, config)
        if not isinstance(events, tuple) or not 1 <= len(events) <= MAX_EVENTS:
            reject("events")
        for event in events:
            if not isinstance(event, InboundEvent):
                reject("schema")
            for key in (event.event_key, event.endpoint_key, event.namespace):
                if (
                    not isinstance(key, str)
                    or not key
                    or len(key) > 256
                    or key != key.strip()
                    or "\x00" in key
                ):
                    reject("key")
            for key in (event.sender_key, event.thread_key, event.message_key):
                if not isinstance(key, str) or len(key) > 256 or "\x00" in key:
                    reject("key")
            if not isinstance(event.body, str) or len(event.body) > 65536 or "\x00" in event.body:
                reject("body")
            if event.kind not in ("message", "edit", "receipt", "unsupported"):
                reject("kind")
            if (
                type(event.private) is not bool
                or type(event.revision) is not int
                or not 0 <= event.revision <= 2147483647
            ):
                reject("schema")
            if event.kind in ("message", "edit"):
                for key in (event.sender_key, event.thread_key, event.message_key):
                    if (
                        not isinstance(key, str)
                        or not key
                        or len(key) > 256
                        or key != key.strip()
                        or "\x00" in key
                    ):
                        reject("key")
                if (
                    not isinstance(event.body, str)
                    or not event.body.strip()
                    or len(event.body) > 65536
                    or "\x00" in event.body
                ):
                    reject("body")
                parsed = datetime.strptime(event.occurred_at, "%Y-%m-%d %H:%M:%S")
                if parsed.year < 2000 or parsed > datetime.now(UTC).replace(
                    tzinfo=None,
                ) + timedelta(minutes=5):
                    reject("timestamp")
        return events, hashlib.sha256(raw).hexdigest()
    except IngressRejected:
        raise
    except Exception:  # noqa: BLE001 - secret-bearing provider exceptions never cross boundary
        reject("invalid")
