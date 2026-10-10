"""Identity checks must use the same read-only path as Verify bot."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from odoo.addons.omni_telegram.providers.telegram import TelegramAdapter
from odoo.addons.omni_telegram.providers.transport import HTTPResult


class TestReadonlyHealth(unittest.TestCase):
    def test_sender_health_uses_readonly_verification(self):
        transport = Mock()
        transport.call.return_value = HTTPResult(200, {
            'ok': True, 'result': {'id': 123456789, 'is_bot': True},
        })
        adapter = TelegramAdapter(transport, lambda _ref, _config: SimpleNamespace(token='synthetic'))
        result = adapter.check_sender_health({
            'account_key': '123456789', 'namespace': '123456789',
            'sender_key': '123456789', 'credential_reference': 'synthetic',
            'adapter': {'sandbox_authorized': False, 'sandbox_recipients': ['987654321']},
        })
        self.assertTrue(result.healthy)
        transport.call.assert_called_once_with('synthetic', 'getMe', {}, verify_only=True)
