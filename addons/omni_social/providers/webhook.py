"""Pure signature/challenge checks and account-bound notification hints."""

import hashlib
import hmac
import json
import re


def signature(provider, secret, raw, header):
    if not secret or not isinstance(raw, bytes) or len(raw) > 524288 or not isinstance(header, str):
        return False
    if provider not in ('instagram', 'linkedin') or not re.fullmatch(
        r'sha256=[0-9a-f]{64}' if provider == 'instagram' else r'[0-9a-f]{64}', header
    ):
        return False
    message = raw if provider == 'instagram' else b'hmacsha256=' + raw
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if provider == 'instagram':
        expected = 'sha256=' + expected
    return hmac.compare_digest(expected, header)


def challenge(provider, secret, verify, params):
    # An unset token or secret must never validate an empty or forged challenge.
    if provider == 'instagram' and not verify:
        raise ValueError('verification')
    if provider != 'instagram' and not secret:
        raise ValueError('verification')
    if provider == 'instagram':
        value = params.get('hub.challenge', '')
        if params.get('hub.mode') != 'subscribe' or not hmac.compare_digest(
            str(params.get('hub.verify_token', '')).encode(), verify.encode()
        ):
            raise ValueError('verification')
        if not isinstance(value, str) or not 1 <= len(value) <= 1024:
            raise ValueError('challenge')
        return value
    value = params.get('challengeCode', '')
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError('challenge')
    return {
        'challengeCode': value,
        'challengeResponse': hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest(),
    }


def hints(provider, profile, raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('payload')
    if provider == 'instagram':
        entries = value.get('entry', [])
        if value.get('object') not in ('instagram', 'page') or not isinstance(entries, list) or len(entries) > 100:
            raise ValueError('payload')
        # Signed hints cannot authorize replies or supply trusted message content.
        return [
            hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            for e in entries
            if isinstance(e, dict) and str(e.get('id')) in (profile['id'], profile['page'])
        ]
    if value.get('type') != 'ORGANIZATION_SOCIAL_ACTION_NOTIFICATIONS':
        raise ValueError('event')
    events = value.get('notifications', [])
    if not isinstance(events, list) or len(events) > 100:
        raise ValueError('payload')
    result = []
    for event in events:
        if (
            not isinstance(event, dict)
            or event.get('organizationalEntity') != profile['id']
            or event.get('subscriber') != profile['member']
        ):
            continue
        identity = event.get('notificationId')
        modified = event.get('lastModifiedAt')
        if not isinstance(identity, int) or isinstance(identity, bool) or not isinstance(modified, int):
            raise ValueError('notification')
        result.append(hashlib.sha256(f'{identity}:{modified}'.encode()).hexdigest())
    return result
