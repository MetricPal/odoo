"""One explicitly authorized setup diagnostic, separate from business replies."""
from .transport import TelegramHTTP
from .secrets import canonical_id

TEST_MESSAGE = 'Telegram connection test successful.'


def send_test_message(token, recipient, transport=None):
    """No retries. Only a confirmed rejection is safe to try again."""
    transport = transport or TelegramHTTP()
    recipient = canonical_id(recipient)
    try:
        response = transport.call(token, 'getChat', {'chat_id': recipient}, test_message=True)
        chat = response.data.get('result', {})
        if response.status != 200 or response.data.get('ok') is not True or chat.get('type') != 'private' or canonical_id(chat.get('id')) != recipient:
            return 'failed', 'start_bot'
    except Exception:
        return 'failed', 'unreachable'
    try:
        response = transport.call(token, 'sendMessage', {
            'chat_id': recipient, 'text': TEST_MESSAGE,
            'link_preview_options': {'is_disabled': True},
        }, test_message=True)
        data = response.data
        if isinstance(data, dict) and data.get('ok') is False and data.get('error_code') == response.status and response.status in (400, 401, 403, 404, 429):
            return 'failed', 'rejected'
        message = data.get('result', {})
        if response.status == 200 and data.get('ok') is True and message.get('text') == TEST_MESSAGE and message.get('chat', {}).get('type') == 'private' and canonical_id(message['chat']['id']) == recipient and message.get('from', {}).get('is_bot') is True and canonical_id(message['from']['id']) == token.split(':')[0]:
            return 'sent', canonical_id(message['message_id'])
    except Exception:
        pass
    return 'unknown', 'unconfirmed'
