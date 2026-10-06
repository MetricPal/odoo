import json
import stat
import tempfile
import unittest
from pathlib import Path

from provision_sandbox_secret import provision


class TestProvision(unittest.TestCase):
    def test_private_creation_scope_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'secret.json'
            provision(path, 'sandbox', 1, '123', '123:' + 'x' * 32)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            bundle = json.loads(path.read_text())
            self.assertEqual(bundle['database'], 'sandbox')
            self.assertEqual(bundle['company_id'], 1)
            self.assertEqual(bundle['bot_id'], '123')
            self.assertGreaterEqual(len(bundle['webhook_secret']), 32)
            with self.assertRaises(FileExistsError):
                provision(path, 'sandbox', 1, '123', '123:' + 'x' * 32)

    def test_wrong_identity_and_shared_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'secret.json'
            with self.assertRaises(ValueError):
                provision(path, 'sandbox', 1, '123', '456:' + 'x' * 32)
            Path(directory).chmod(0o755)
            with self.assertRaises(ValueError):
                provision(path, 'sandbox', 1, '123', '123:' + 'x' * 32)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
