"""Bounded server-to-server transport. Never accept URLs or routes from a model."""
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit

import urllib3

from odoo import _
from odoo.exceptions import UserError

MAX_RESPONSE = 1024 * 1024


class HermesUncertain(UserError):
    """The remote operation may have been accepted; never repeat blindly."""


def target(url, resolve=True):
    try:
        parsed = urlsplit(url or '')
        port = parsed.port or (80 if parsed.scheme == 'http' else 443)
    except ValueError:
        raise UserError(_('Enter a valid Hermes HTTPS address.')) from None
    allowed = {v.strip().lower() for v in os.getenv('AI_AGENT_ENDPOINTS', '').split(',') if v.strip()}
    authority = f'{parsed.hostname}:{port}'.lower()
    loopback_http = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', '::1')
    if (parsed.scheme != 'https' and not loopback_http or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or authority not in allowed):
        raise UserError(_('Use HTTPS, or numeric localhost HTTP, on an origin provisioned in AI_AGENT_ENDPOINTS.'))
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


def request(url, secret_reference, method, path, payload=None, headers=None):
    if method not in ('GET', 'POST') or not re.fullmatch(r'/[a-zA-Z0-9_./-]+', path) or '..' in path:
        raise UserError(_('Unsupported Hermes operation.'))
    parsed, addresses, port = target(url)
    key = credential(secret_reference)
    options = {'port': port, 'timeout': urllib3.Timeout(connect=5, read=20), 'retries': False}
    if parsed.scheme == 'https':
        options.update(assert_hostname=parsed.hostname, server_hostname=parsed.hostname)
        pool = urllib3.HTTPSConnectionPool(addresses[0], **options)
    else:
        if any(not ipaddress.ip_address(ip).is_loopback for ip in addresses):
            raise UserError(_('Local HTTP must resolve exclusively to loopback addresses.'))
        pool = urllib3.HTTPConnectionPool(addresses[0], **options)
    response = None
    try:
        response = pool.request(method, path, body=json.dumps(payload).encode() if payload is not None else None,
                                headers={'Host': parsed.netloc, 'Authorization': f'Bearer {key}',
                                         'Content-Type': 'application/json', **(headers or {})},
                                redirect=False, preload_content=False, retries=False)
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('response too large')
        if not 200 <= response.status < 300:
            raise ValueError('remote status')
        return json.loads(raw)
    except (OSError, ValueError, urllib3.exceptions.HTTPError):
        if method == 'POST':
            raise HermesUncertain(_('Hermes acceptance is uncertain. The operation will not be repeated automatically.')) from None
        raise UserError(_('Hermes could not return a valid response. Check its readiness and credentials.')) from None
    finally:
        if response is not None:
            response.release_conn()
        pool.close()
