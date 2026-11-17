"""Business messaging on the Cloud API: send one approved template, submit and read templates.

Pure protocol code: no ORM, no logging, no retries. Fixed Graph host, bearer token outside the URL, bounded
responses. A POST that may have reached Meta is never reported as "not sent". Meta's error texts stay inside this
module except a template's rejection reason, which is bounded and shown to the person who wrote the template.
"""
import json
import re
import time
from urllib.parse import urlencode

import requests

from .connection import HOST

MAX_RESPONSE = 256 * 1024
MAX_TEMPLATES = 1000
MAX_PAGES = 10
STATUSES = {'APPROVED': 'approved', 'PENDING': 'review', 'IN_APPEAL': 'review', 'REJECTED': 'rejected',
            'PAUSED': 'paused', 'DISABLED': 'rejected', 'LIMIT_EXCEEDED': 'rejected'}
# Meta error codes (WhatsApp Cloud API). Anything else after a rejection is "the template or the number".
RATE_CODES = {4, 80007, 130429, 131048, 131056}
TOKEN_CODES = {0, 3, 10, 190, 200}
RECIPIENT_CODES = {131026, 131021, 131030, 131050, 130472}
TEMPLATE_CODES = {132000, 132001, 132005, 132007, 132012, 132015, 132016}
DAILY_LIMIT_CODES = {131049, 131053}


class BusinessRejected(ValueError):
    """``args[0]`` is a fixed code; ``detail`` is a bounded text from Meta, safe to show to the template's author."""

    def __init__(self, code, detail=''):
        super().__init__(code)
        self.detail = detail


def _valid_version(version):
    return isinstance(version, str) and re.fullmatch(r'v[1-9][0-9]{0,2}\.0', version) is not None


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,31}', value) is not None


def _valid_token(token):
    return (isinstance(token, str) and 0 < len(token) <= 8192 and token.isascii()
            and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in token))


def template_name(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z0-9_]{1,512}', value) is not None


def language_code(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z]{2,3}(_[A-Z]{2})?', value) is not None


def parameter(value):
    """A value for a numbered field: one line, no tabs, no run of four spaces (Meta refuses those)."""
    return (isinstance(value, str) and 0 < len(value) <= 1024 and '\x00' not in value
            and not re.search(r'[\n\r\t]| {4}', value))


def _session():
    return requests.Session()  # resolved at call time so tests can replace it


def _read(response, deadline):
    chunks, length = [], 0
    for chunk in response.iter_content(4096):
        if time.monotonic() >= deadline:
            raise TimeoutError
        length += len(chunk)
        if length > MAX_RESPONSE:
            raise ValueError('size')
        chunks.append(chunk)
    return json.loads(b''.join(chunks))


def _error(data):
    error = data.get('error') if isinstance(data, dict) else None
    if isinstance(error, dict) and type(error.get('code')) is int:
        return error
    return None


def _detail(error):
    parts = [error.get('error_user_msg'), error.get('error_user_title'), error.get('message')]
    text = next((part for part in parts if isinstance(part, str) and part.strip()), '')
    return ' '.join(text.split())[:300]


# ------------------------------------------------------------------ sending one template message

def template_payload(recipient, template):
    """The request body for one template message, or None when the input is not exactly what is supported."""
    if not isinstance(template, dict) or not _identifier(recipient):
        return None
    name, language, values = template.get('name'), template.get('language'), template.get('body', [])
    if (not template_name(name) or not language_code(language) or not isinstance(values, list) or len(values) > 10
            or not all(parameter(value) for value in values)
            or set(template) - {'name', 'language', 'body'}):
        return None
    components = []
    if values:
        components.append({'type': 'body', 'parameters': [{'type': 'text', 'text': value} for value in values]})
    return {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': recipient, 'type': 'template',
            'template': {'name': name, 'language': {'code': language}, 'components': components}}


def send_template(version, phone, token, recipient, template):
    """One POST. Returns ``(outcome, detail, retry_after)``.

    outcome: ``accepted`` (detail = Meta's message id), ``not_sent`` (detail = rate_limited | daily_limit |
    unauthorized | invalid_recipient | template | configuration) or ``unknown``.
    """
    body = template_payload(recipient, template)
    if not _valid_version(version) or not _identifier(phone) or not _valid_token(token) or body is None:
        return 'not_sent', 'configuration', 0
    try:
        deadline = time.monotonic() + 25
        with _session() as session:
            session.trust_env = False
            with session.post(f'{HOST}/{version}/{phone}/messages', headers={'Authorization': 'Bearer ' + token},
                              json=body, timeout=(5, 20), verify=True, allow_redirects=False,
                              stream=True) as response:
                data = _read(response, deadline)
                error = _error(data)
                if response.status_code in (400, 401, 403, 404, 429) and error:
                    code = error['code']
                    if response.status_code == 429 or code in RATE_CODES:
                        return 'not_sent', 'rate_limited', 60
                    if code in DAILY_LIMIT_CODES:
                        return 'not_sent', 'daily_limit', 3600
                    if response.status_code == 401 or code in TOKEN_CODES:
                        return 'not_sent', 'unauthorized', 0
                    if code in RECIPIENT_CODES:
                        return 'not_sent', 'invalid_recipient', 0
                    return 'not_sent', 'template', 0
                if (response.status_code == 200 and isinstance(data, dict)
                        and data.get('messaging_product') == 'whatsapp'
                        and isinstance(data.get('messages'), list) and len(data['messages']) == 1):
                    message = data['messages'][0].get('id') if isinstance(data['messages'][0], dict) else None
                    if isinstance(message, str) and re.fullmatch(r'[A-Za-z0-9_.:@+/=-]{1,256}', message):
                        return 'accepted', message, 0
    except Exception:  # noqa: BLE001 - a timeout or a broken answer may follow a successful send
        pass
    return 'unknown', 'unconfirmed', 0


# ------------------------------------------------------------------ templates: submit, read

def template_components(*, body, example, header='', footer='', button_label='', button_url=''):
    """Meta's components for a text template. ``body`` already uses numbered fields ({{1}}, {{2}})."""
    if not isinstance(body, str) or not 0 < len(body) <= 1024:
        raise BusinessRejected('body')
    numbers = [int(number) for number in re.findall(r'\{\{(\d+)\}\}', body)]
    if sorted(set(numbers)) != list(range(1, len(set(numbers)) + 1)) or len(example) != len(set(numbers)):
        raise BusinessRejected('fields')
    components = []
    if header:
        if len(header) > 60 or '{{' in header or '\n' in header:
            raise BusinessRejected('header')
        components.append({'type': 'HEADER', 'format': 'TEXT', 'text': header})
    part = {'type': 'BODY', 'text': body}
    if example:
        if not all(parameter(value) for value in example):
            raise BusinessRejected('example')
        part['example'] = {'body_text': [list(example)]}
    components.append(part)
    if footer:
        if len(footer) > 60 or '{{' in footer or '\n' in footer:
            raise BusinessRejected('footer')
        components.append({'type': 'FOOTER', 'text': footer})
    if button_label or button_url:
        if (not 0 < len(button_label) <= 25 or not isinstance(button_url, str) or len(button_url) > 2000
                or re.fullmatch(r'https://[^\s{}]+', button_url) is None):
            raise BusinessRejected('button')
        components.append({'type': 'BUTTONS', 'buttons': [{'type': 'URL', 'text': button_label, 'url': button_url}]})
    return components


def submit_template(version, business_account_id, token, *, name, language, components):
    """Create a marketing template at Meta. Returns ``{'id', 'status'}``; raises BusinessRejected.

    ``unknown`` means the request may have reached Meta: read the templates before submitting again.
    """
    if (not _valid_version(version) or not _identifier(business_account_id) or not _valid_token(token)
            or not template_name(name) or not language_code(language)):
        raise BusinessRejected('configuration')
    try:
        deadline = time.monotonic() + 25
        with _session() as session:
            session.trust_env = False
            with session.post(f'{HOST}/{version}/{business_account_id}/message_templates',
                              headers={'Authorization': 'Bearer ' + token},
                              json={'name': name, 'language': language, 'category': 'MARKETING',
                                    'components': components},
                              timeout=(5, 20), verify=True, allow_redirects=False, stream=True) as response:
                data = _read(response, deadline)
                error = _error(data)
                if response.status_code in (400, 401, 403, 404, 429) and error:
                    if response.status_code == 429 or error['code'] in RATE_CODES:
                        raise BusinessRejected('rate_limited')
                    if response.status_code == 401 or error['code'] in TOKEN_CODES:
                        raise BusinessRejected('credentials')
                    raise BusinessRejected('refused', _detail(error))
                if (response.status_code == 200 and isinstance(data, dict) and _identifier(str(data.get('id', '')))
                        and data.get('status') in STATUSES):
                    return {'id': str(data['id']), 'status': STATUSES[data['status']]}
    except BusinessRejected:
        raise
    except Exception:  # noqa: BLE001
        pass
    raise BusinessRejected('unknown')


def list_templates(version, business_account_id, token):
    """Every template of the business account: ``[{id, name, language, status, reason}]``. GET only."""
    if not _valid_version(version) or not _identifier(business_account_id) or not _valid_token(token):
        raise BusinessRejected('configuration')
    found, cursor, seen = [], None, set()
    deadline = time.monotonic() + 25
    try:
        with _session() as session:
            session.trust_env = False
            for _page in range(MAX_PAGES):
                query = {'fields': 'id,name,language,status,rejected_reason,category', 'limit': '100'}
                if cursor:
                    query['after'] = cursor
                url = f'{HOST}/{version}/{business_account_id}/message_templates?{urlencode(query)}'
                with session.get(url, headers={'Authorization': 'Bearer ' + token}, timeout=(5, 10),
                                 verify=True, allow_redirects=False, stream=True) as response:
                    if response.status_code in (401, 403):
                        raise BusinessRejected('credentials')
                    if response.status_code == 429:
                        raise BusinessRejected('rate_limited')
                    if response.status_code != 200:
                        raise BusinessRejected('provider')
                    data = _read(response, deadline)
                if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                    raise BusinessRejected('response')
                for item in data['data']:
                    if not isinstance(item, dict) or item.get('status') not in STATUSES:
                        continue  # a kind or a status this version does not know: leave it alone
                    key = str(item.get('id', ''))
                    if not _identifier(key) or not template_name(item.get('name')) or key in seen:
                        continue
                    seen.add(key)
                    reason = item.get('rejected_reason')
                    reason = reason if isinstance(reason, str) and reason not in ('', 'NONE') else ''
                    found.append({'id': key, 'name': item['name'], 'language': item.get('language') or '',
                                  'status': STATUSES[item['status']], 'reason': reason[:120]})
                    if len(found) > MAX_TEMPLATES:
                        raise BusinessRejected('size')
                paging = data.get('paging') if isinstance(data.get('paging'), dict) else {}
                cursors = paging.get('cursors') if isinstance(paging.get('cursors'), dict) else {}
                # Never follow Meta's "next" address; only its cursor, on the same fixed resource.
                cursor = cursors.get('after') if paging.get('next') else None
                if not cursor:
                    return found
                if not isinstance(cursor, str) or len(cursor) > 1024:
                    raise BusinessRejected('response')
    except BusinessRejected:
        raise
    except Exception:  # noqa: BLE001
        raise BusinessRejected('network') from None
    raise BusinessRejected('size')
