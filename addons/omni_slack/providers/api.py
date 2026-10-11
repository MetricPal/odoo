"""Fixed Slack Web API endpoints; bounded responses and no automatic retries."""
import json
import re
import time
import requests

TEST_MESSAGE = 'Slack connection test successful.'
ID = re.compile(r'[A-Z][A-Z0-9]{1,63}')

class SlackRejected(ValueError):
    pass

def valid_id(value, prefix):
    return isinstance(value, str) and ID.fullmatch(value) is not None and value.startswith(prefix)

def call(method, token, values=None, *, session_factory=requests.Session):
    if method not in ('auth.test', 'conversations.info', 'chat.postMessage') or not isinstance(token, str) or not token.startswith('xoxb-') or len(token) > 8192 or any(c.isspace() or ord(c) < 32 for c in token):
        raise SlackRejected('credentials')
    deadline = time.monotonic() + 20
    with session_factory() as session:
        session.trust_env = False
        request = session.get if method == 'conversations.info' else session.post
        arguments = {'params': values or {}} if method == 'conversations.info' else {'json': values or {}}
        with request('https://slack.com/api/' + method, headers={'Authorization': 'Bearer ' + token},
                          **arguments, timeout=(5, 10), verify=True, allow_redirects=False, stream=True) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(1):
                size += len(chunk)
                if size > 32768 or time.monotonic() > deadline:
                    raise SlackRejected('response')
                chunks.append(chunk)
            data = json.loads(b''.join(chunks))
            if response.status_code != 200 or not isinstance(data, dict) or type(data.get('ok')) is not bool:
                raise SlackRejected('response')
            return data

def verify(token):
    try:
        data = call('auth.test', token)
        if not data.get('ok') or not valid_id(data.get('team_id'), 'T') or not valid_id(data.get('user_id'), 'U') or not valid_id(data.get('bot_id'), 'B'):
            raise SlackRejected('credentials')
        return {key: data[key] for key in ('team_id', 'user_id', 'bot_id')} | {'name': str(data.get('team', 'Slack'))[:128]}
    except Exception:
        raise SlackRejected('credentials') from None

def send_text(token, recipient, text):
    if not valid_id(recipient, 'D') or not isinstance(text, str) or not text.strip() or len(text) > 4000 or '\x00' in text:
        raise SlackRejected('recipient')
    try:
        data = call('chat.postMessage', token, {'channel': recipient, 'text': text,
                     'unfurl_links': False, 'unfurl_media': False})
        if data['ok'] is False:
            # Only known definitive rejections allow a new human-confirmed attempt.
            if data.get('error') in ('invalid_auth','token_revoked','account_inactive','missing_scope','not_in_channel','channel_not_found','is_archived','restricted_action','no_permission','ratelimited'):
                return 'failed', 'rejected'
        elif data.get('channel') == recipient and isinstance(data.get('ts'), str) and re.fullmatch(r'[0-9]{10}\.[0-9]{6}', data['ts']):
            return 'accepted', data['ts']
    except Exception:
        pass
    return 'unknown', 'unconfirmed'


def send_test(token, recipient):
    return send_text(token, recipient, TEST_MESSAGE)
