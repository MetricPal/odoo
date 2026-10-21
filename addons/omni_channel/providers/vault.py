"""Encrypted private credential files shared by Omnichannel provider addons.

Odoo records hold only an opaque reference such as ``OMNI_SECRET_SLACK_<hex>``.
The bundle is encrypted with Fernet and stored under the Odoo data directory,
one folder per provider and per database. Files must be owned by the Odoo
process user and must not be readable by group or others.

Encryption key
--------------
By default the key lives in ``<folder>/key`` beside the encrypted files, which
protects against accidental disclosure (backups of the database alone, file
listings) but not against someone who can read the data directory.

Set ``OMNI_VAULT_KEY`` (a Fernet key, see ``Fernet.generate_key()``) in the
Odoo process environment to keep the key outside the data directory. New
bundles are then encrypted with it, while existing bundles written with the
key file stay readable, so the switch needs no migration. To rotate, put the
new key first and the old one after it, comma-separated.
"""

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

KEY_ENVIRONMENT = "OMNI_VAULT_KEY"
MAX_FILE = 16384
MAX_BUNDLE = 10000


def _private(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("storage")


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("storage")
        value = stream.read(MAX_FILE + 1)
        if len(value) > MAX_FILE:
            raise ValueError("size")
        return value


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _environment_keys():
    raw = os.environ.get(KEY_ENVIRONMENT, "")
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    try:
        return [Fernet(key) for key in keys]
    except (ValueError, TypeError):
        raise ValueError("key") from None


class CredentialVault:
    """One provider's encrypted credential store.

    ``scope_keys`` name the provider identifiers (besides database, company
    and purpose) that a bundle must match when it is loaded, so a reference
    copied to another connection or database cannot be used there.
    """

    def __init__(self, prefix, folder, scope_keys):
        self.prefix = prefix
        self.folder = folder
        self.scope_keys = tuple(scope_keys)

    def _root(self, database, data_dir=None):
        if data_dir is None:
            from odoo.tools import config  # noqa: PLC0415 - lazy: usable outside a server
            data_dir = config["data_dir"]
        return Path(data_dir) / self.folder / hashlib.sha256(database.encode()).hexdigest()

    def _file(self, reference):
        if not isinstance(reference, str) or re.fullmatch(re.escape(self.prefix) + r"[A-F0-9]{32}", reference) is None:
            raise ValueError("reference")
        return reference + ".bin"

    def _file_key(self, root, create=False):
        key = root / "key"
        if create and not key.exists():
            temporary = root / (".key-" + uuid.uuid4().hex)
            try:
                _write(temporary, Fernet.generate_key())
                try:
                    os.link(temporary, key)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        return Fernet(_read(key)) if key.exists() else None

    def _cipher(self, root, create=False):
        keys = _environment_keys()
        file_key = self._file_key(root, create=create and not keys)
        if file_key:
            keys.append(file_key)
        if not keys:
            raise ValueError("key")
        return MultiFernet(keys)

    def store(self, bundle, data_dir=None):
        root = self._root(bundle["database"], data_dir)
        _private(root.parent)
        _private(root)
        reference = self.prefix + uuid.uuid4().hex.upper()
        content = json.dumps(bundle).encode()
        if len(content) > MAX_BUNDLE:
            raise ValueError("size")
        _write(root / self._file(reference), self._cipher(root, create=True).encrypt(content))
        return reference

    def load(self, reference, *, database, company_id, purpose_id, data_dir=None, **scope):
        if set(scope) != set(self.scope_keys):
            raise ValueError("scope")
        root = self._root(database, data_dir)
        try:
            content = self._cipher(root).decrypt(_read(root / self._file(reference)))
        except InvalidToken:
            raise ValueError("key") from None
        value = json.loads(content)
        expected = {"database": database, "company_id": company_id, "purpose_id": purpose_id, **scope}
        if any(value.get(key) != wanted for key, wanted in expected.items()):
            raise ValueError("scope")
        return value

    def remove(self, reference, database, data_dir=None):
        (self._root(database, data_dir) / self._file(reference)).unlink(missing_ok=True)
