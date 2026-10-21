"""Bot Connector RS256 authentication; tenant-bound personal Teams text only."""

import base64
import json
import re
import threading
import time
from datetime import datetime, UTC
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from .api import request_json, service_url, valid_id

ISSUER = 'https://api.botframework.com'
METADATA = 'https://login.botframework.com/v1/.well-known/openidconfiguration'
KEYS = 'https://login.botframework.com/v1/.well-known/keys'
_cache = {}
_lock = threading.Lock()


def pairs(items):
    value = {}
    for k, v in items:
        if k in value:
            raise ValueError('duplicate')
        value[k] = v
    return value


def decode(segment):
    if not isinstance(segment, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', segment):
        raise ValueError('jwt')
    return base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))


def signing_keys(kid):
    now = time.monotonic()
    with _lock:
        cached = _cache.get('keys', [])
        if _cache.get('expires', 0) > now and any(k.get('kid') == kid for k in cached):
            return cached
        if now - _cache.get('fetched', -100) < 30:
            raise ValueError('key')
        _cache['fetched'] = now
        status, meta = request_json('get', METADATA)
        if (
            status != 200
            or not isinstance(meta, dict)
            or meta.get('issuer') != ISSUER
            or meta.get('jwks_uri') != KEYS
            or 'RS256' not in meta.get('id_token_signing_alg_values_supported', [])
        ):
            raise ValueError('metadata')
        status, data = request_json('get', KEYS)
        if (
            status != 200
            or not isinstance(data, dict)
            or not isinstance(data.get('keys'), list)
            or not 1 <= len(data['keys']) <= 100
        ):
            raise ValueError('keys')
        _cache.update(keys=data['keys'], expires=now + 86400)
        return data['keys']


def authenticate(raw, headers, app_id, tenant_id, *, keys=None, now=None):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1024 * 1024:
        raise ValueError('size')
    headers = {k.lower(): v for k, v in headers.items()}
    bearer = headers.get('authorization', '')
    if not isinstance(bearer, str) or not bearer.startswith('Bearer ') or len(bearer) > 16384:
        raise ValueError('authorization')
    parts = bearer[7:].split('.')
    if len(parts) != 3:
        raise ValueError('jwt')
    header = json.loads(decode(parts[0]), object_pairs_hook=pairs)
    claims = json.loads(decode(parts[1]), object_pairs_hook=pairs)
    if (
        not isinstance(header, dict)
        or not isinstance(claims, dict)
        or header.get('alg') != 'RS256'
        or header.get('crit')
        or header.get('jku')
        or header.get('x5u')
    ):
        raise ValueError('algorithm')
    kid = header.get('kid')
    if not isinstance(kid, str) or not 1 <= len(kid) <= 256:
        raise ValueError('key')
    candidates = signing_keys(kid) if keys is None else keys
    matching = [k for k in candidates if k.get('kid') == kid]
    if len(matching) != 1:
        raise ValueError('key')
    key = matching[0]
    if key.get('kty') != 'RSA' or key.get('use', 'sig') != 'sig' or 'msteams' not in key.get('endorsements', []):
        raise ValueError('endorsement')
    n, e = int.from_bytes(decode(key['n']), 'big'), int.from_bytes(decode(key['e']), 'big')
    if n.bit_length() < 2048 or n.bit_length() > 8192 or e not in (3, 65537):
        raise ValueError('key')
    rsa.RSAPublicNumbers(e, n).public_key().verify(
        decode(parts[2]), ('.'.join(parts[:2])).encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    clock = time.time() if now is None else now
    if (
        claims.get('iss') != ISSUER
        or claims.get('aud') != app_id
        or type(claims.get('exp')) is not int
        or type(claims.get('nbf')) is not int
        or claims['exp'] <= claims['nbf']
        or clock > claims['exp'] + 300
        or clock < claims['nbf'] - 300
    ):
        raise ValueError('claims')
    value = json.loads(raw, object_pairs_hook=pairs)
    if (
        not isinstance(value, dict)
        or value.get('channelId') != 'msteams'
        or claims.get('serviceurl', claims.get('serviceUrl')) != value.get('serviceUrl')
    ):
        raise ValueError('service')
    service_url(value.get('serviceUrl'))
    tenant = value.get('channelData', {}).get('tenant', {}).get('id')
    if tenant != tenant_id or value.get('recipient', {}).get('id') != '28:' + app_id:
        raise ValueError('scope')
    return value


def message(value):
    key = value.get('id')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:@+/=-]{1,256}', key):
        raise ValueError('event')
    conversation = value.get('conversation', {})
    if (
        value.get('type') != 'message'
        or conversation.get('conversationType') != 'personal'
        or any(
            not isinstance(a, dict) or a.get('contentType') != 'text/html' or a.get('contentUrl')
            for a in value.get('attachments', [])
        )
        or value.get('textFormat', 'plain') != 'plain'
        or value.get('from', {}).get('role') == 'bot'
    ):
        return key, None
    sender = value.get('from', {})
    user, member = sender.get('aadObjectId'), sender.get('id')
    thread, text = conversation.get('id'), value.get('text')
    if (
        not valid_id(user)
        or not isinstance(member, str)
        or not member.startswith('29:')
        or len(member) > 256
        or not isinstance(thread, str)
        or not thread.startswith('a:')
        or len(thread) > 256
        or not isinstance(text, str)
        or not text.strip()
        or len(text) > 65536
        or '\x00' in text
    ):
        raise ValueError('message')
    stamp = datetime.fromisoformat(value['timestamp'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp')
    return key, {
        'user': user,
        'member_id': member,
        'thread': thread,
        'text': text,
        'service_url': value['serviceUrl'],
        'occurred': stamp.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S'),
    }
