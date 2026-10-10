"""Read-only bot verification with safe, actionable failure categories."""
import re
import secrets

from .secrets import TelegramConfigurationError, canonical_id
from .transport import TelegramHTTP


class TelegramSetupError(TelegramConfigurationError):
    """Only a fixed category crosses this boundary, never provider response text."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__()


def prepare_credentials(token, webhook_secret, database, company_id, transport=None):
    """Return a scoped bundle and public identity, never send/register anything."""
    if not isinstance(token, str) or not re.fullmatch(r'[1-9][0-9]{0,15}:[A-Za-z0-9_-]{20,128}', token):
        raise TelegramSetupError('token_format')
    secret = webhook_secret or secrets.token_urlsafe(32)
    if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise TelegramSetupError('secret_format')
    try:
        response = (transport or TelegramHTTP()).call(token, 'getMe', {}, verify_only=True)
    except Exception:
        raise TelegramSetupError('transport') from None
    if response.status in (401, 404):
        raise TelegramSetupError('rejected')
    if response.status == 429:
        raise TelegramSetupError('rate_limit')
    if response.status >= 500:
        raise TelegramSetupError('unavailable')
    try:
        data = response.data
        result = data.get('result') if isinstance(data, dict) else None
        if response.status != 200 or data.get('ok') is not True or not isinstance(result, dict) or result.get('is_bot') is not True:
            raise ValueError()
        bot = canonical_id(result.get('id'))
        if bot != token.split(':', 1)[0]:
            raise ValueError()
        name, username = result.get('first_name', ''), result.get('username', '')
        if not isinstance(name, str) or not isinstance(username, str) or len(name) > 256 or len(username) > 256:
            raise ValueError()
    except Exception:
        raise TelegramSetupError('identity') from None
    return {
        'database': database, 'company_id': company_id, 'bot_id': bot,
        'token': token, 'webhook_secret': secret,
    }, {'telegram_bot_name': name, 'telegram_bot_username': username}


def verify_webhook(token, expected_url, transport=None):
    """Check registered URL only; never register, send, or claim actual delivery."""
    if not expected_url or not expected_url.startswith('https://'):
        raise TelegramSetupError('callback_missing')
    try:
        response = (transport or TelegramHTTP()).call(token, 'getWebhookInfo', {}, verify_only=True)
    except Exception:
        raise TelegramSetupError('transport') from None
    if response.status in (401, 404):
        raise TelegramSetupError('rejected')
    if response.status == 429:
        raise TelegramSetupError('rate_limit')
    if response.status >= 500:
        raise TelegramSetupError('unavailable')
    data = response.data
    result = data.get('result') if isinstance(data, dict) else None
    if response.status != 200 or not isinstance(data, dict) or data.get('ok') is not True or not isinstance(result, dict) or not isinstance(result.get('url'), str):
        raise TelegramSetupError('webhook_response')
    if not result['url']:
        raise TelegramSetupError('webhook_absent')
    if result['url'] != expected_url:
        raise TelegramSetupError('webhook_mismatch')
    # Telegram may report an earlier delivery failure; never echo its raw text.
    return bool(result.get('last_error_date'))


def webhook_info(token, transport=None):
    try:
        response = (transport or TelegramHTTP()).call(token, 'getWebhookInfo', {}, verify_only=True)
    except Exception:
        raise TelegramSetupError('transport') from None
    if response.status in (401, 404):
        raise TelegramSetupError('rejected')
    if response.status == 429:
        raise TelegramSetupError('rate_limit')
    if response.status >= 500:
        raise TelegramSetupError('unavailable')
    data = response.data
    result = data.get('result') if isinstance(data, dict) else None
    if response.status != 200 or not isinstance(result, dict) or data.get('ok') is not True or not isinstance(result.get('url'), str):
        raise TelegramSetupError('webhook_response')
    return result


def register_webhook(token, secret, url, transport=None):
    """Explicit registration, never drop pending updates or retry a mutation."""
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment and not parsed.query
    except ValueError:
        valid = False
    if not valid:
        raise TelegramSetupError('callback_missing')
    if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise TelegramSetupError('secret_format')
    client = transport or TelegramHTTP()
    try:
        response = client.call(token, 'setWebhook', {
            'url': url, 'secret_token': secret,
            'allowed_updates': ['message', 'edited_message'],
            'drop_pending_updates': False,
        }, register_webhook=True)
    except Exception:
        raise TelegramSetupError('registration_unknown') from None
    if response.status in (400, 401, 403, 404, 429):
        raise TelegramSetupError('registration_rejected')
    data = response.data
    if response.status != 200 or not isinstance(data, dict) or data.get('ok') is not True or data.get('result') is not True:
        raise TelegramSetupError('registration_unknown')
    try:
        info = webhook_info(token, client)
    except TelegramSetupError:
        raise TelegramSetupError('registration_unconfirmed') from None
    updates = info.get('allowed_updates')
    if info['url'] != url or not isinstance(updates, list) or not all(isinstance(item, str) for item in updates) or not {'message', 'edited_message'}.issubset(set(updates)):
        raise TelegramSetupError('registration_unconfirmed')
    return bool(info.get('last_error_date'))
