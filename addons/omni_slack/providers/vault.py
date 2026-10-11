"""Encrypted private files. Odoo records contain only opaque references."""
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

PREFIX = "OMNI_SECRET_SLACK_"


def _root(database, data_dir=None):
    if data_dir is None:
        from odoo.tools import config
        data_dir = config["data_dir"]
    return Path(data_dir) / "omni_slack_credentials" / hashlib.sha256(database.encode()).hexdigest()


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
        value = stream.read(16385)
        if len(value) > 16384:
            raise ValueError("size")
        return value


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _file(reference):
    if not isinstance(reference, str) or re.fullmatch(PREFIX + r"[A-F0-9]{32}", reference) is None:
        raise ValueError("reference")
    return reference + ".bin"


def _key(root):
    key = root / "key"
    if not key.exists():
        temporary = root / (".key-" + uuid.uuid4().hex)
        try:
            _write(temporary, Fernet.generate_key())
            try:
                os.link(temporary, key)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    return _read(key)


def store(bundle, data_dir=None):
    root = _root(bundle["database"], data_dir)
    _private(root.parent)
    _private(root)
    reference = PREFIX + uuid.uuid4().hex.upper()
    content = json.dumps(bundle).encode()
    if len(content) > 10000:
        raise ValueError("size")
    _write(root / _file(reference), Fernet(_key(root)).encrypt(content))
    return reference


def load(reference, *, database, company_id, purpose_id, bot_id, workspace_id, data_dir=None):
    root = _root(database, data_dir)
    content = Fernet(_read(root / "key")).decrypt(_read(root / _file(reference)))
    value = json.loads(content)
    scope = {"database": database, "company_id": company_id, "purpose_id": purpose_id,
             "bot_id": bot_id, "workspace_id": workspace_id}
    if any(value.get(key) != expected for key, expected in scope.items()):
        raise ValueError("scope")
    return value


def remove(reference, database, data_dir=None):
    (_root(database, data_dir) / _file(reference)).unlink(missing_ok=True)
