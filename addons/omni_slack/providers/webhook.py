"""Authenticate original bytes before parsing; private human text only."""
import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime

MAX_BODY = 1024 * 1024

def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result

def authenticated(raw, headers, secret, now=None):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY or not isinstance(secret, str) or not secret:
        raise ValueError('signature')
    headers = {key.lower(): value for key, value in headers.items()}
    stamp, signature = headers.get('x-slack-request-timestamp', ''), headers.get('x-slack-signature', '')
    if not isinstance(stamp, str) or not re.fullmatch(r'[0-9]{10}', stamp) or abs((time.time() if now is None else now) - int(stamp)) > 300:
        raise ValueError('timestamp')
    expected = 'v0=' + hmac.new(secret.encode(), b'v0:' + stamp.encode() + b':' + raw, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ValueError('signature')
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError('schema')
    return value

def challenge(value):
    result = value.get('challenge')
    if value.get('type') != 'url_verification' or not isinstance(result, str) or not 1 <= len(result) <= 256 or not result.isascii() or any(ord(c) < 32 for c in result):
        raise ValueError('challenge')
    return result

def message(value, workspace, app_id):
    if value.get('type') != 'event_callback' or value.get('team_id') != workspace or value.get('api_app_id') != app_id:
        raise ValueError('scope')
    key = value.get('event_id')
    if not isinstance(key, str) or not re.fullmatch(r'Ev[A-Za-z0-9]{1,64}', key):
        raise ValueError('event')
    event = value.get('event', {})
    if not isinstance(event, dict):
        raise ValueError('event')
    # Do not ingest public/group messages, edits, files, bot messages or threaded replies.
    if (event.get('type') != 'message' or event.get('channel_type') != 'im' or event.get('subtype')
            or event.get('bot_id') or event.get('thread_ts') or event.get('files')):
        return key, None
    user, channel, text, stamp = (event.get(k) for k in ('user', 'channel', 'text', 'ts'))
    if (not isinstance(user, str) or not re.fullmatch(r'U[A-Z0-9]{1,63}', user)
            or not isinstance(channel, str) or not re.fullmatch(r'D[A-Z0-9]{1,63}', channel)
            or not isinstance(text, str) or not text.strip() or len(text) > 65536 or '\x00' in text
            or not isinstance(stamp, str) or not re.fullmatch(r'[0-9]{10}\.[0-9]{6}', stamp)):
        raise ValueError('message')
    occurred = datetime.fromtimestamp(float(stamp), UTC).strftime('%Y-%m-%d %H:%M:%S')
    return key, {'user': user, 'channel': channel, 'text': text, 'stamp': stamp, 'occurred': occurred}
