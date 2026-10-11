"""One fixed, explicitly confirmed diagnostic. Never retries a POST."""
import json
import re
import time

import requests

from .connection import HOST

TEST_MESSAGE = 'WhatsApp connection test successful.'


def send_test(version, phone, token, recipient, session_factory=requests.Session):
    if (not isinstance(version, str) or not re.fullmatch(r'v[1-9][0-9]{0,2}\.0', version)
            or any(not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', value)
                   for value in (phone, recipient))
            or not isinstance(token, str) or not 0 < len(token) <= 8192
            or not token.isascii() or any(char.isspace() or ord(char) < 32 for char in token)):
        raise ValueError('configuration')
    try:
        deadline = time.monotonic() + 25
        with session_factory() as session:
            session.trust_env = False
            with session.post(HOST + '/' + version + '/' + phone + '/messages',
                              headers={'Authorization': 'Bearer ' + token},
                              json={'messaging_product': 'whatsapp', 'recipient_type': 'individual',
                                    'to': recipient, 'type': 'text',
                                    'text': {'body': TEST_MESSAGE, 'preview_url': False}},
                              timeout=(5, 10), verify=True, allow_redirects=False, stream=True) as response:
                chunks, length = [], 0
                # Small chunks let the elapsed-time limit catch slow-drip responses.
                for chunk in response.iter_content(1):
                    if time.monotonic() >= deadline:
                        return 'unknown', 'unconfirmed'
                    length += len(chunk)
                    if length > 16384:
                        return 'unknown', 'unconfirmed'
                    chunks.append(chunk)
                data = json.loads(b''.join(chunks))
                if (response.status_code in (400, 401, 403, 404, 429)
                        and isinstance(data, dict) and isinstance(data.get('error'), dict)
                        and type(data['error'].get('code')) is int):
                    return 'failed', 'rejected'
                if (response.status_code == 200 and data.get('messaging_product') == 'whatsapp'
                        and len(data.get('contacts', [])) == 1 and len(data.get('messages', [])) == 1
                        and data['contacts'][0].get('wa_id') == recipient):
                    message = data['messages'][0].get('id')
                    if isinstance(message, str) and message.startswith('wamid.') and len(message) <= 256:
                        return 'accepted', message
    except Exception:
        pass  # A timeout, disconnect or malformed response may follow a successful send.
    return 'unknown', 'unconfirmed'
