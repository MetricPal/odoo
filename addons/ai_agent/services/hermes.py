"""Bounded server-to-server transport. Never accept URLs or routes from a model."""
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import urlencode, urlsplit

import urllib3

from odoo import _
from odoo.exceptions import UserError

MAX_RESPONSE = 1024 * 1024


class HermesUncertain(UserError):
    """The remote operation may have been accepted; never repeat blindly."""


class HermesRejected(UserError):
    """Hermes definitively refused the request (4xx); nothing was accepted."""

    status = None  # The HTTP status, when Hermes answered.


class HermesUnavailable(UserError):
    """A read-only request failed. Safe to retry later."""


class HermesBusy(UserError):
    """Hermes is at its concurrent-run cap (HTTP 429) and accepted nothing: try again after ``retry_after`` seconds."""

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


# 408 Request Timeout and 429 Too Many Requests do not prove the POST was refused.
DEFINITIVE_REJECTIONS = frozenset(range(400, 500)) - {408, 429}


# Loopback ports of the local Hermes profile; demo connections may use them without the deployment allowlist.
DEMO_LOOPBACK = frozenset({'127.0.0.1:8643', '127.0.0.1:9120'})


def target(url, resolve=True, demo=False):
    if not isinstance(url, str) or not url.strip():
        raise UserError(_('Enter the Hermes server URL, for example https://hermes.example.com.'))
    if url != url.strip() or any(character.isspace() or ord(character) < 32 for character in url):
        raise UserError(_('The Hermes URL must not contain spaces or control characters.'))
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if port is None:
            port = 80 if parsed.scheme == 'http' else 443
        if not 1 <= port <= 65535:
            raise ValueError('invalid port')
    except ValueError:
        raise UserError(_('Enter a valid server URL with a port between 1 and 65535.')) from None
    if not parsed.scheme or not parsed.hostname:
        raise UserError(_('Enter a complete Hermes server URL, for example https://hermes.example.com.'))
    if parsed.username is not None or parsed.password is not None:
        raise UserError(_('Remove the username or password from the URL. Enter credentials in the API key field.'))
    loopback_http = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', '::1')
    if parsed.scheme != 'https' and not loopback_http:
        raise UserError(_('Remote Hermes requires HTTPS. HTTP is allowed only for 127.0.0.1 or ::1 on the application server.'))
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise UserError(_('Enter the Hermes server base URL only, for example https://hermes.example.com. Remove page paths, search parameters and fragments.'))
    allowed = {v.strip().lower() for v in os.getenv('AI_AGENT_ENDPOINTS', '').split(',') if v.strip()}
    if demo:
        allowed |= DEMO_LOOPBACK
    authority = f'{parsed.hostname}:{port}'.lower()
    if authority not in allowed:
        raise UserError(_('This server (%s) is not approved for AI Agent connections. Ask your system administrator to add this host and port to the deployment endpoint allowlist (AI_AGENT_ENDPOINTS), then restart the application server.', authority))
    addresses = []
    if resolve:
        try:
            addresses = sorted({v[4][0] for v in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)})
        except OSError:
            raise UserError(_('Hermes address could not be resolved.')) from None
        if not addresses or any(ipaddress.ip_address(v).is_link_local
                                or ipaddress.ip_address(v).is_unspecified
                                or ipaddress.ip_address(v).is_multicast for v in addresses):
            raise UserError(_('Hermes resolves to a prohibited network address.'))
    return parsed, addresses, port


def credential(reference):
    if not re.fullmatch(r'AI_AGENT_SECRET_[A-Z0-9_]{1,80}', reference or ''):
        raise UserError(_('Select a provisioned AI_AGENT_SECRET_ reference.'))
    key = os.getenv(reference)
    if not key or '\n' in key or '\r' in key:
        raise UserError(_('The Hermes credential has not been provisioned.'))
    return key


# Writes Odoo makes: runs (POST) and, on the management API, profile configuration (PUT/PATCH/DELETE).
WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
# Query parameters Odoo sends, and the values each may take.
QUERY_VALUES = {'profile': re.compile(r'[a-z0-9][a-z0-9_-]{0,63}'),
                'provider': re.compile(r'[a-z0-9][a-z0-9_.:-]{0,99}'),
                'include_unconfigured': re.compile(r'true')}


def _problem(status, path, where):
    """A plain explanation of a Hermes error status, or None."""
    if status in (401, 403):
        return _('Hermes at %(where)s refused the key (HTTP %(status)s). Check the credential.', where=where, status=status)
    if status == 404:
        return _('Hermes at %(where)s has no %(path)s (HTTP 404). Check the address and the Hermes version.',
                 where=where, path=path.split('?')[0])
    return None


# The live event stream of a run (Hermes ``GET /v1/runs/{id}/events``, server-sent events).
TERMINAL_RUN_EVENTS = frozenset({'run.completed', 'run.failed', 'run.cancelled', 'run.interrupted', 'done'})
STREAM_LINE_MAX = 1024 * 1024


def run_events(url, path, *, credential_value, demo=False, deadline_seconds=900):
    """Yield the event names Hermes streams for one run, until it ends or ``deadline_seconds`` pass.

    Same address checks and key handling as :func:`request`. Any network trouble just ends the stream: the caller
    falls back to asking for the run's status.
    """
    if not re.fullmatch(r'/[a-zA-Z0-9_./-]+', path) or '..' in path:
        raise UserError(_('Unsupported Hermes operation.'))
    parsed, addresses, port = target(url, demo=demo)
    key = credential_value
    if not isinstance(key, str) or not key or len(key) > 4096 or '\n' in key or '\r' in key:
        raise UserError(_('Configure a valid API key.'))
    options = {'port': port, 'timeout': urllib3.Timeout(connect=5, read=120), 'retries': False}
    if parsed.scheme == 'https':
        options.update(assert_hostname=parsed.hostname, server_hostname=parsed.hostname)
        pool = urllib3.HTTPSConnectionPool(addresses[0], **options)
    else:
        if any(not ipaddress.ip_address(ip).is_loopback for ip in addresses):
            raise UserError(_('Local HTTP must resolve exclusively to loopback addresses.'))
        pool = urllib3.HTTPConnectionPool(addresses[0], **options)
    deadline = time.monotonic() + deadline_seconds
    response = None
    try:
        response = pool.request('GET', path, headers={'Host': parsed.netloc, 'Authorization': f'Bearer {key}',
                                                     'Accept': 'text/event-stream'},
                                redirect=False, preload_content=False, retries=False)
        if response.status != 200:
            return
        for raw in response:
            if time.monotonic() > deadline or len(raw) > STREAM_LINE_MAX:
                return
            line = raw.decode('utf-8', 'replace').strip()
            if line.startswith('event:'):
                name = line[len('event:'):].strip()
                yield name
                if name in TERMINAL_RUN_EVENTS:
                    return
            elif line.startswith('data:'):
                try:
                    data = json.loads(line[len('data:'):].strip())
                except ValueError:
                    continue
                name = data.get('event') or data.get('type') if isinstance(data, dict) else None
                if isinstance(name, str):
                    yield name
                    if name in TERMINAL_RUN_EVENTS:
                        return
    except (OSError, urllib3.exceptions.HTTPError):
        return
    finally:
        if response is not None:
            response.release_conn()
        pool.close()


def request(url, secret_reference, method, path, payload=None, headers=None, *, credential_value=None, demo=False,
            query=None):
    if method not in WRITE_METHODS | {'GET'} or not re.fullmatch(r'/[a-zA-Z0-9_./-]+', path) or '..' in path:
        raise UserError(_('Unsupported Hermes operation.'))
    if query:
        if any(k not in QUERY_VALUES or not isinstance(v, str) or not QUERY_VALUES[k].fullmatch(v)
               for k, v in query.items()):
            raise UserError(_('Unsupported Hermes operation.'))
        path = f'{path}?{urlencode(query)}'
    parsed, addresses, port = target(url, demo=demo)
    key = credential_value if credential_value is not None else credential(secret_reference)
    if not isinstance(key, str) or not key or len(key) > 4096 or '\n' in key or '\r' in key:
        raise UserError(_('Configure a valid API key.'))
    options = {'port': port, 'timeout': urllib3.Timeout(connect=5, read=20), 'retries': False}
    if parsed.scheme == 'https':
        options.update(assert_hostname=parsed.hostname, server_hostname=parsed.hostname)
        pool = urllib3.HTTPSConnectionPool(addresses[0], **options)
    else:
        if any(not ipaddress.ip_address(ip).is_loopback for ip in addresses):
            raise UserError(_('Local HTTP must resolve exclusively to loopback addresses.'))
        pool = urllib3.HTTPConnectionPool(addresses[0], **options)
    response = None
    where = f'{parsed.hostname}:{port}'
    try:
        response = pool.request(method, path, body=json.dumps(payload).encode() if payload is not None else None,
                                headers={'Host': parsed.netloc, 'Authorization': f'Bearer {key}',
                                         'Content-Type': 'application/json', **(headers or {})},
                                redirect=False, preload_content=False, retries=False)
    except urllib3.exceptions.ConnectTimeoutError:
        # Includes "connection refused": nothing reached Hermes, so nothing was submitted.
        pool.close()
        message = _('Hermes is not running or cannot be reached at %s. Start it, or check the address.', where)
        error = (HermesRejected if method in WRITE_METHODS else HermesUnavailable)(message)
        error.unreachable = True
        raise error from None
    except (OSError, urllib3.exceptions.HTTPError):
        pool.close()
        if method == 'POST':
            raise HermesUncertain(_('Hermes acceptance is uncertain. The operation will not be repeated automatically.')) from None
        raise HermesUnavailable(_('Hermes at %s did not answer in time. Check that it is running.', where)) from None
    try:
        status = response.status
        if method in WRITE_METHODS and status in DEFINITIVE_REJECTIONS:
            rejection = HermesRejected(_problem(status, path, where) or _('Hermes refused the request (HTTP %s). Nothing was submitted; check the agent configuration and credentials.', status))
            rejection.status = status
            raise rejection
        if status == 429 and method == 'POST':
            # Hermes checks its run cap before it reserves anything (verified on Hermes v0.21: the idempotency
            # reservation comes after the cap), so nothing was accepted and the same request may be sent again.
            try:
                retry_after = max(0, min(300, int(response.headers.get('Retry-After') or 0)))
            except ValueError:
                retry_after = 0
            raise HermesBusy(_('Hermes at %s is busy (all its run slots are taken). Try again shortly.', where),
                             retry_after)
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('response too large')
        if not 200 <= status < 300:
            if method == 'POST':
                raise ValueError('remote status')
            raise HermesUnavailable(_problem(status, path, where)
                                    or _('Hermes at %(where)s answered with an error (HTTP %(status)s).', where=where, status=status))
        return json.loads(raw)
    except (OSError, ValueError, urllib3.exceptions.HTTPError):
        if method == 'POST':
            raise HermesUncertain(_('Hermes acceptance is uncertain. The operation will not be repeated automatically.')) from None
        raise HermesUnavailable(_('Hermes at %s answered with something that is not valid data. Check the address and the Hermes version.', where)) from None
    finally:
        if response is not None:
            response.release_conn()
        pool.close()
