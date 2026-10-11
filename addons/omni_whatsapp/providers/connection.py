"""Read-only WhatsApp business-account verification, separate from activation."""

import json
import queue
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

HOST = "https://graph.facebook.com"
MAX_RESPONSE = 1024 * 1024
MAX_PAGES = 5
MAX_NUMBERS = 250
MAX_SECONDS = 25
_READ_SLOTS = threading.BoundedSemaphore(4)


class ConnectionRejected(ValueError):
    """Fixed codes only. Graph error bodies and access tokens never escape."""


@dataclass(frozen=True)
class PhoneNumber:
    id: str
    name: str
    number: str


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,31}", value) is not None


def _label(value):
    if not isinstance(value, str) or not 0 < len(value) <= 256 or any(ord(c) < 32 for c in value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class GraphReadOnly:
    """Fixed Graph host/resource; GET only, no redirects, proxies or automatic retries."""

    def __init__(self, version, session_factory=None):
        # Deployment supplies a currently supported version; never silently upgrade.
        if not isinstance(version, str) or re.fullmatch(r"v[1-9][0-9]{0,2}\.0", version) is None:
            raise ConnectionRejected("version")
        self.version = version
        self.session_factory = session_factory or requests.Session
        self.deadline = time.monotonic() + MAX_SECONDS

    def phone_numbers(self, business_account_id, access_token, cursor=None):
        # A fresh client is created per verification workflow. Its entire
        # pagination shares this deadline, including slow DNS or streaming.
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or not _READ_SLOTS.acquire(blocking=False):
            raise ConnectionRejected("network")
        result = queue.Queue(maxsize=1)

        def read():
            try:
                result.put((True, self._phone_numbers(business_account_id, access_token, cursor)))
            except ConnectionRejected as error:
                result.put((False, str(error)))
            except Exception:
                result.put((False, "network"))
            finally:
                _READ_SLOTS.release()

        # Only GET happens in this worker: no ORM, file writes or external
        # mutations. Slow reads can outlive the caller but cannot grow unbounded.
        threading.Thread(target=read, daemon=True).start()
        try:
            success, value = result.get(timeout=remaining)
        except queue.Empty:
            raise ConnectionRejected("network") from None
        if not success:
            raise ConnectionRejected(value)
        return value

    def _phone_numbers(self, business_account_id, access_token, cursor=None):
        if not _identifier(business_account_id):
            raise ConnectionRejected("account")
        if (not isinstance(access_token, str) or not 1 <= len(access_token) <= 8192
                or not access_token.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in access_token)):
            raise ConnectionRejected("credentials")
        if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024):
            raise ConnectionRejected("paging")
        query = {"fields": "id,verified_name,display_phone_number", "limit": "50"}
        if cursor is not None:
            query["after"] = cursor
        url = f"{HOST}/{self.version}/{business_account_id}/phone_numbers?{urlencode(query)}"
        try:
            with self.session_factory() as session:
                session.trust_env = False
                with session.get(url, headers={"Authorization": "Bearer " + access_token},
                                 timeout=(5, 10), allow_redirects=False, stream=True, verify=True) as response:
                    if response.status_code in (401, 403):
                        raise ConnectionRejected("credentials")
                    if response.status_code == 429:
                        raise ConnectionRejected("rate_limited")
                    if response.status_code != 200:
                        raise ConnectionRejected("provider")
                    content = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        if time.monotonic() >= self.deadline:
                            raise ConnectionRejected("network")
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE:
                            raise ConnectionRejected("size")
                    return json.loads(content)
        except ConnectionRejected:
            raise
        except (requests.RequestException, OSError):
            raise ConnectionRejected("network") from None
        except (ValueError, TypeError, RecursionError):
            raise ConnectionRejected("response") from None


def verify_account(transport, business_account_id, access_token):
    """List owned numbers. Verifies read access, not sending permission or delivery."""
    if not _identifier(business_account_id):
        raise ConnectionRejected("account")
    numbers, seen_ids, seen_cursors = [], set(), set()
    cursor = None
    for _ in range(MAX_PAGES):
        result = transport.phone_numbers(business_account_id, access_token, cursor)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ConnectionRejected("response")
        for item in result["data"]:
            if not isinstance(item, dict) or not _identifier(item.get("id")):
                raise ConnectionRejected("response")
            name, number = item.get("verified_name"), item.get("display_phone_number")
            if not _label(name) or not _label(number) or item["id"] in seen_ids:
                raise ConnectionRejected("response")
            seen_ids.add(item["id"])
            numbers.append(PhoneNumber(item["id"], name, number))
            if len(numbers) > MAX_NUMBERS:
                raise ConnectionRejected("size")
        paging = result.get("paging", {})
        if not isinstance(paging, dict):
            raise ConnectionRejected("paging")
        if not paging.get("next"):
            if not numbers:
                raise ConnectionRejected("no_numbers")
            return tuple(numbers)
        # Never request the supplied next URL: it can contain credentials or a
        # foreign host. Only extract a cursor for the same fixed account resource.
        cursors = paging.get("cursors")
        cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024 or cursor in seen_cursors:
            raise ConnectionRejected("paging")
        seen_cursors.add(cursor)
    raise ConnectionRejected("paging_limit")


def select_phone(numbers, phone_number_id=None):
    """Auto-select a single number; multiple numbers require an explicit choice."""
    if not numbers:
        raise ConnectionRejected("no_numbers")
    if phone_number_id is None:
        if len(numbers) == 1:
            return numbers[0]
        raise ConnectionRejected("choose_number")
    for number in numbers:
        if number.id == phone_number_id:
            return number
    raise ConnectionRejected("number_scope")
