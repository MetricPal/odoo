import os
import tempfile
from unittest.mock import patch

from cryptography.fernet import Fernet

from odoo.tests import TransactionCase, tagged

from ..providers.vault import KEY_ENVIRONMENT, CredentialVault


@tagged('post_install', '-at_install')
class TestSharedVault(TransactionCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.vault = CredentialVault('OMNI_SECRET_TEST_', 'omni_test_credentials', ('bot_id', 'workspace_id'))
        self.bundle = {'database': 'db1', 'company_id': 1, 'purpose_id': 2, 'bot_id': 'B1',
                       'workspace_id': 'W1', 'token': 'secret-value'}

    def _load(self, reference, **overrides):
        values = {'database': 'db1', 'company_id': 1, 'purpose_id': 2, 'bot_id': 'B1', 'workspace_id': 'W1',
                  'data_dir': self.directory.name, **overrides}
        return self.vault.load(reference, **values)

    def test_round_trip_and_scope(self):
        reference = self.vault.store(self.bundle, self.directory.name)
        self.assertEqual(self._load(reference)['token'], 'secret-value')
        with self.assertRaises(ValueError):
            self._load(reference, workspace_id='W2')
        with self.assertRaises(ValueError):
            self.vault._file('../escape')
        stored = (self.vault._root('db1', self.directory.name) / self.vault._file(reference)).read_bytes()
        self.assertNotIn(b'secret-value', stored)

    def test_environment_key_keeps_old_bundles_readable(self):
        legacy = self.vault.store(self.bundle, self.directory.name)
        env_key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {KEY_ENVIRONMENT: env_key}):
            self.assertEqual(self._load(legacy)['token'], 'secret-value')
            fresh = self.vault.store(self.bundle, self.directory.name)
            self.assertEqual(self._load(fresh)['token'], 'secret-value')
        # Written with the environment key only: unreadable without it.
        with self.assertRaises(ValueError):
            self._load(fresh)

    def test_environment_key_only_never_writes_a_key_file(self):
        with patch.dict(os.environ, {KEY_ENVIRONMENT: Fernet.generate_key().decode()}):
            reference = self.vault.store(self.bundle, self.directory.name)
            self.assertEqual(self._load(reference)['token'], 'secret-value')
        self.assertFalse((self.vault._root('db1', self.directory.name) / 'key').exists())

    def test_invalid_environment_key_is_rejected(self):
        with patch.dict(os.environ, {KEY_ENVIRONMENT: 'not-a-key'}), self.assertRaises(ValueError):
            self.vault.store(self.bundle, self.directory.name)
