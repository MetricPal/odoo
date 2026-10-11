import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("omni_whatsapp_vault_test", Path(__file__).resolve().parents[1] / "providers/vault.py")
vault = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vault)


class TestVault(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bundle = {"database": "synthetic_database", "company_id": 1, "purpose_id": 2,
                       "phone_number_id": "123", "business_account_id": "456", "access_token": "synthetic_token_only"}
        self.scope = {key: value for key, value in self.bundle.items() if key != "access_token"}

    def test_encrypted_roundtrip_and_private_permissions(self):
        reference = vault.store(self.bundle, self.directory.name)
        self.assertEqual(vault.load(reference, data_dir=self.directory.name, **self.scope), self.bundle)
        root = vault._root(self.bundle["database"], self.directory.name)
        for path in (root.parent, root, root / "key", root / vault._file(reference)):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertNotIn(self.bundle["access_token"].encode(), (root / vault._file(reference)).read_bytes())

    def test_cross_scope_and_database_rejected(self):
        reference = vault.store(self.bundle, self.directory.name)
        for key in self.scope:
            changed = {**self.scope, key: "foreign" if isinstance(self.scope[key], str) else 99}
            with self.subTest(key=key), self.assertRaises(Exception):
                vault.load(reference, data_dir=self.directory.name, **changed)

    def test_reference_cannot_traverse_directories(self):
        for reference in ("../../token", "OMNI_SECRET_WHATSAPP_../key", None):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                vault._file(reference)

    def test_world_readable_storage_rejected(self):
        reference = vault.store(self.bundle, self.directory.name)
        root = vault._root(self.bundle["database"], self.directory.name)
        os.chmod(root / vault._file(reference), 0o644)
        with self.assertRaises(ValueError):
            vault.load(reference, data_dir=self.directory.name, **self.scope)

    def test_symlink_secret_rejected(self):
        reference = vault.store(self.bundle, self.directory.name)
        root = vault._root(self.bundle["database"], self.directory.name)
        (root / vault._file(reference)).unlink()
        (root / vault._file(reference)).symlink_to(root / "key")
        with self.assertRaises(OSError):
            vault.load(reference, data_dir=self.directory.name, **self.scope)

    def test_cleanup_is_idempotent(self):
        reference = vault.store(self.bundle, self.directory.name)
        vault.remove(reference, self.bundle["database"], self.directory.name)
        vault.remove(reference, self.bundle["database"], self.directory.name)
        with self.assertRaises(FileNotFoundError):
            vault.load(reference, data_dir=self.directory.name, **self.scope)
