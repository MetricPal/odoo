"""Database-free runtime storage and verification regression tests."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# Load provider modules without starting an Odoo registry or registering adapters.
ROOT = Path(__file__).resolve().parents[1] / 'providers'
PACKAGE = '_telegram_runtime_tests'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

def module(name):
    spec = importlib.util.spec_from_file_location(PACKAGE + '.' + name, ROOT / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value

secrets = module('secrets')
storage = module('runtime_secrets')
transport = module('transport')
setup = module('setup')
TOKEN = '123456789:synthetic_token_for_local_tests_only'

class FakeTransport:
    def __init__(self, bot=123456789):
        self.bot = bot
        self.calls = []
    def call(self, token, method, payload, **kwargs):
        self.calls.append((method, payload, kwargs))
        return transport.HTTPResult(200, {'ok': True, 'result': {
            'id': self.bot, 'is_bot': True, 'first_name': 'Test bot', 'username': 'test_bot',
        }})

class TestRuntimeCredentials(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        original = storage._root
        self.patcher = patch.object(storage, '_root', lambda database, data_dir=None: original(database, self.directory.name))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_verify_generates_secret_and_only_calls_getme(self):
        client = FakeTransport()
        bundle, identity = setup.prepare_credentials(TOKEN, '', 'test_database', 7, client)
        self.assertEqual(identity['telegram_bot_username'], 'test_bot')
        self.assertEqual(bundle['bot_id'], '123456789')
        self.assertEqual(bundle['company_id'], 7)
        self.assertGreaterEqual(len(bundle['webhook_secret']), 32)
        self.assertEqual(client.calls, [('getMe', {}, {'verify_only': True})])

    def test_encrypted_roundtrip_permissions_and_scope(self):
        bundle, _identity = setup.prepare_credentials(TOKEN, '', 'test_database', 7, FakeTransport())
        ref = storage.store(bundle)
        root = storage._root('test_database')
        encrypted = (root / (ref + '.bin')).read_bytes()
        self.assertNotIn(TOKEN.encode(), encrypted)
        self.assertEqual((root / (ref + '.bin')).stat().st_mode & 0o777, 0o600)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(storage.load(ref, 'test_database')), bundle)
        config = {'account_key': '123456789', 'namespace': '123456789', 'adapter': {'database': 'test_database', 'company_id': 7}}
        self.assertEqual(secrets.resolve(ref, config).token, TOKEN)
        for field, bad in [('database', 'copied_database'), ('company_id', 8)]:
            changed = dict(config, adapter=dict(config['adapter'], **{field: bad}))
            with self.assertRaises(secrets.TelegramConfigurationError):
                secrets.resolve(ref, changed)
        storage.remove(ref, 'test_database')
        with self.assertRaises(secrets.TelegramConfigurationError):
            secrets.resolve(ref, config)

    def test_invalid_inputs_fail_before_network_and_never_echo_secrets(self):
        for token, secret in [('not-a-telegram-token', ''), (TOKEN, 'too-short'), (TOKEN, 'x' * 257)]:
            client = FakeTransport()
            with self.assertRaises(secrets.TelegramConfigurationError) as error:
                setup.prepare_credentials(token, secret, 'test_database', 7, client)
            self.assertEqual(client.calls, [])
            self.assertNotIn(token, str(error.exception))

    def test_mismatched_bot_and_transport_failure(self):
        with self.assertRaises(secrets.TelegramConfigurationError):
            setup.prepare_credentials(TOKEN, '', 'test_database', 7, FakeTransport(9))
        client = FakeTransport()
        client.call = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError(TOKEN))
        with self.assertRaises(secrets.TelegramConfigurationError) as error:
            setup.prepare_credentials(TOKEN, '', 'test_database', 7, client)
        self.assertNotIn(TOKEN, str(error.exception))

    def test_custom_secret_and_tampering(self):
        bundle, _ = setup.prepare_credentials(TOKEN, 'a' * 32, 'db', 1, FakeTransport())
        self.assertEqual(bundle['webhook_secret'], 'a' * 32)
        ref = storage.store(bundle)
        (storage._root('db') / (ref + '.bin')).write_bytes(b'corrupt')
        with self.assertRaises(Exception):
            storage.load(ref, 'db')
        with self.assertRaises(ValueError):
            storage.load('../key', 'db')

    def test_legacy_environment_reference_remains_supported(self):
        bundle, _ = setup.prepare_credentials(TOKEN, '', 'db', 1, FakeTransport())
        config = {'account_key': '123456789', 'namespace': '123456789', 'adapter': {'database': 'db', 'company_id': 1}}
        self.assertEqual(secrets.resolve('OMNI_SECRET_LEGACY', config, {'OMNI_SECRET_LEGACY': json.dumps(bundle)}).token, TOKEN)

    def test_verification_option_does_not_enable_sending(self):
        with patch.dict('os.environ', {'OMNI_TELEGRAM_SANDBOX_NETWORK': '0'}):
            for method in ('sendMessage', 'getChat'):
                with self.assertRaises(transport.TelegramTransportError):
                    transport.TelegramHTTP().call(TOKEN, method, {}, verify_only=True)

class TestSetupFailureCategories(unittest.TestCase):
    def test_input_failures_are_distinct_and_never_echo_secrets(self):
        for token, secret, expected in [('bad', '', 'token_format'), (TOKEN, 'short', 'secret_format')]:
            client = FakeTransport()
            with self.assertRaises(setup.TelegramSetupError) as raised:
                setup.prepare_credentials(token, secret, 'db', 1, client)
            self.assertEqual(raised.exception.reason, expected)
            self.assertNotIn(TOKEN, str(raised.exception))
            self.assertFalse(client.calls)

    def test_provider_failures_are_distinct_and_sanitized(self):
        for status, expected in [(401, 'rejected'), (404, 'rejected'), (429, 'rate_limit'), (503, 'unavailable'), (200, 'identity')]:
            with self.subTest(status=status), patch.object(FakeTransport, 'call', return_value=transport.HTTPResult(status, {'description': TOKEN})):
                with self.assertRaises(setup.TelegramSetupError) as raised:
                    setup.prepare_credentials(TOKEN, '', 'db', 1, FakeTransport())
                self.assertEqual(raised.exception.reason, expected)
                self.assertNotIn(TOKEN, str(raised.exception))
        with patch.object(FakeTransport, 'call', side_effect=RuntimeError(TOKEN)):
            with self.assertRaises(setup.TelegramSetupError) as raised:
                setup.prepare_credentials(TOKEN, '', 'db', 1, FakeTransport())
            self.assertEqual(raised.exception.reason, 'transport')
            self.assertNotIn(TOKEN, str(raised.exception))

class TestWebhookVerification(unittest.TestCase):
    URL = 'https://channels.example.com/omni/inbound/test-route'

    def check_response(self, status, data):
        client = FakeTransport()
        with patch.object(client, 'call', return_value=transport.HTTPResult(status, data)) as call:
            result = setup.verify_webhook(TOKEN, self.URL, client)
        call.assert_called_once_with(TOKEN, 'getWebhookInfo', {}, verify_only=True)
        return result

    def test_matching_registration_and_previous_error(self):
        self.assertFalse(self.check_response(200, {'ok': True, 'result': {'url': self.URL}}))
        self.assertTrue(self.check_response(200, {'ok': True, 'result': {'url': self.URL, 'last_error_date': 1}}))

    def test_absent_mismatch_and_malformed_are_not_success(self):
        for data, reason in [
            ({'ok': True, 'result': {'url': ''}}, 'webhook_absent'),
            ({'ok': True, 'result': {'url': 'https://elsewhere.example/secret'}}, 'webhook_mismatch'),
            ({'ok': True, 'result': {}}, 'webhook_response'),
            (None, 'webhook_response'),
        ]:
            with self.subTest(reason=reason), self.assertRaises(setup.TelegramSetupError) as error:
                self.check_response(200, data)
            self.assertEqual(error.exception.reason, reason)
            self.assertNotIn('secret', str(error.exception))

    def test_network_and_provider_errors_are_sanitized(self):
        for status, reason in [(401, 'rejected'), (429, 'rate_limit'), (503, 'unavailable')]:
            with self.assertRaises(setup.TelegramSetupError) as error:
                self.check_response(status, {'description': TOKEN})
            self.assertEqual(error.exception.reason, reason)
            self.assertNotIn(TOKEN, str(error.exception))
        with patch.object(FakeTransport, 'call', side_effect=RuntimeError(TOKEN)):
            with self.assertRaises(setup.TelegramSetupError) as error:
                setup.verify_webhook(TOKEN, self.URL, FakeTransport())
            self.assertEqual(error.exception.reason, 'transport')

    def test_missing_url_does_not_call_provider(self):
        client = FakeTransport()
        with self.assertRaises(setup.TelegramSetupError):
            setup.verify_webhook(TOKEN, '', client)
        self.assertEqual(client.calls, [])

if __name__ == '__main__':
    unittest.main()
