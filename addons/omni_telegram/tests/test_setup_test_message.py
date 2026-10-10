"""Fixed diagnostic transport cannot send arbitrary business messages."""
import unittest
from unittest.mock import Mock, patch

from odoo.addons.omni_telegram.providers.test_message import TEST_MESSAGE, send_test_message
from odoo.addons.omni_telegram.providers.transport import HTTPResult, TelegramHTTP, TelegramTransportError

TOKEN = '123456789:synthetic_token_for_local_tests_only'
RECIPIENT = '987654321'


class TestSetupTestMessage(unittest.TestCase):
    def test_private_chat_then_one_fixed_message(self):
        transport = Mock()
        transport.call.side_effect = [
            HTTPResult(200, {'ok': True, 'result': {'type': 'private', 'id': int(RECIPIENT)}}),
            HTTPResult(200, {'ok': True, 'result': {
                'chat': {'type': 'private', 'id': int(RECIPIENT)},
                'from': {'is_bot': True, 'id': 123456789},
                'text': TEST_MESSAGE, 'message_id': 1,
            }}),
        ]
        self.assertEqual(send_test_message(TOKEN, RECIPIENT, transport), ('sent', '1'))
        self.assertEqual(transport.call.call_count, 2)
        transport.call.assert_called_with(TOKEN, 'sendMessage', {
            'chat_id': RECIPIENT, 'text': TEST_MESSAGE,
            'link_preview_options': {'is_disabled': True},
        }, test_message=True)

    def test_nonprivate_or_wrong_chat_never_sends(self):
        for chat in ({'type': 'group', 'id': -1}, {'type': 'private', 'id': 1}):
            transport = Mock()
            transport.call.return_value = HTTPResult(200, {'ok': True, 'result': chat})
            self.assertEqual(send_test_message(TOKEN, RECIPIENT, transport), ('failed', 'start_bot'))
            self.assertEqual(transport.call.call_count, 1)

    def test_uncertain_send_never_retries(self):
        transport = Mock()
        transport.call.side_effect = [
            HTTPResult(200, {'ok': True, 'result': {'type': 'private', 'id': int(RECIPIENT)}}),
            RuntimeError(TOKEN),
        ]
        self.assertEqual(send_test_message(TOKEN, RECIPIENT, transport), ('unknown', 'unconfirmed'))
        self.assertEqual(transport.call.call_count, 2)

    def test_capability_rejects_arbitrary_payload_or_other_methods(self):
        with patch('odoo.addons.omni_telegram.providers.transport.public_address') as network:
            for method, payload in [
                ('sendMessage', {'chat_id': RECIPIENT, 'text': 'Business message'}),
                ('setWebhook', {}), ('getChat', {'chat_id': RECIPIENT, 'extra': True}),
            ]:
                with self.assertRaises(TelegramTransportError):
                    TelegramHTTP().call(TOKEN, method, payload, test_message=True)
            network.assert_not_called()

    def test_claim_commit_precedes_send_and_result_commit(self):
        from types import SimpleNamespace
        from odoo.addons.omni_telegram.models.telegram import TelegramGuidedSetup
        events = []
        record = Mock()
        record._claim_setup_test.side_effect = lambda: (events.append('claim') or (TOKEN, RECIPIENT))
        record._finish_setup_test.side_effect = lambda *args: events.append('finish')
        cursor = Mock()
        cursor.commit.side_effect = lambda: events.append('commit')
        context = Mock()
        context.__enter__ = Mock(return_value=cursor)
        context.__exit__ = Mock(return_value=False)
        registry = Mock()
        registry.cursor.return_value = context
        model = Mock()
        model.browse.return_value = record
        fresh_env = Mock()
        fresh_env.__getitem__ = Mock(return_value=model)
        channel = SimpleNamespace(
            env=SimpleNamespace(uid=123, lang="en_US", companies=SimpleNamespace(ids=[1]), registry=registry),
            id=1, _name='omni.channel', ensure_one=Mock(), _require_manager=Mock(), invalidate_recordset=Mock(),
        )
        with patch('odoo.addons.omni_telegram.models.telegram.api.Environment', return_value=fresh_env), patch(
            'odoo.addons.omni_telegram.models.telegram.send_test_message',
            side_effect=lambda *args: (events.append('send') or ('sent', '1')),
        ):
            result = TelegramGuidedSetup.action_setup_send_test(channel)
        self.assertEqual(events, ['claim', 'commit', 'send', 'finish', 'commit'])
        self.assertEqual(result['params']['type'], 'success')
