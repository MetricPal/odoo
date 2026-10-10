"""Fixed-host HTTPS, bounded DNS/socket/body budgets, no redirects or retries."""

import http.client
import ipaddress
import json
import os
import queue
import socket
import ssl
import threading
import time
from dataclasses import dataclass

HOST = "api.telegram.org"
MAX_RESPONSE = 1024 * 1024
_DNS_SLOTS = threading.BoundedSemaphore(4)


class TelegramTransportError(Exception):
    def __init__(self):
        super().__init__("Telegram transport failed; outcome may be unknown.")


@dataclass(frozen=True)
class HTTPResult:
    status: int
    data: object


def public_address(timeout=5):
    if not _DNS_SLOTS.acquire(blocking=False):
        raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put(socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM))
        except Exception:  # noqa: BLE001 - sanitize DNS failures
            result.put(None)
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=lookup, daemon=True).start()
    try:
        addresses = result.get(timeout=timeout)
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
        return addresses[0][0], addresses[0][4]
    except Exception:  # noqa: BLE001
        raise TelegramTransportError() from None


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, family, address, deadline):
        super().__init__(HOST, timeout=5, context=ssl.create_default_context())
        self.family, self.address, self.deadline = family, address, deadline
        self.set_debuglevel(0)

    def connect(self):
        # The approved numeric address is used directly; no second DNS lookup.
        sock = socket.socket(self.family, socket.SOCK_STREAM)
        try:
            sock.settimeout(max(0.001, min(5, self.deadline - time.monotonic())))
            sock.connect(self.address)
            sock.settimeout(max(0.001, min(5, self.deadline - time.monotonic())))
            self.sock = self._context.wrap_socket(sock, server_hostname=HOST)
        except Exception:  # noqa: BLE001
            sock.close()
            raise TelegramTransportError() from None


class TelegramHTTP:
    def call(self, token, method, payload, *, verify_only=False):
        if os.environ.get("OMNI_TELEGRAM_SANDBOX_NETWORK") != "1" and not (verify_only and method in ("getMe", "getWebhookInfo")):
            raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
        if method not in ("getMe", "getWebhookInfo", "getChat", "sendMessage"):
            raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
        # All input paths are constructed from a validated token and this enum.
        import re  # noqa: PLC0415

        from .secrets import TelegramConfigurationError  # noqa: PLC0415

        if not isinstance(token, str) or not re.fullmatch(
            r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{20,128}", token,
        ):
            raise TelegramConfigurationError()
        connection = response = timer = None
        deadline = time.monotonic() + 25
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                "utf-8",
            )
            if len(body) > 65536:
                raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
            family, address = public_address()
            connection = PinnedHTTPSConnection(family, address, deadline)
            connection.connect()
            connection.sock.settimeout(max(0.001, min(20, deadline - time.monotonic())))
            connection.request(
                "POST",
                "/bot" + token + "/" + method,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
            )
            # A total deadline also covers a peer trickling HTTP headers.
            active_socket = connection.sock

            def expire():
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(max(0.001, deadline - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            response = http.client.HTTPResponse(active_socket, method="POST")
            response.begin()
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
                connection.sock.settimeout(min(20, remaining))
                chunk = response.read1(min(16384, MAX_RESPONSE + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise TelegramTransportError()  # noqa: TRY301 - sanitized boundary validation
                chunks.append(chunk)
            return HTTPResult(response.status, json.loads(b"".join(chunks)))
        except Exception:  # noqa: BLE001 - do not log token-bearing paths or exceptions
            raise TelegramTransportError() from None
        finally:
            if timer:
                timer.cancel()
            if response:
                response.close()
            if connection:
                connection.close()
