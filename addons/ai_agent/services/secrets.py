"""Private runtime credential files; only opaque references enter Odoo records.

The directory is shared by workers like Odoo's filestore. Back it up separately
from database dumps. Copying a database does not change the embedded binding.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from cryptography.fernet import Fernet

PREFIX = 'AI_AGENT_SECRET_RUNTIME_'


def _root(database, data_dir=None):
    if data_dir is None:
        from odoo.tools import config
        data_dir = config['data_dir']
    return Path(data_dir) / 'ai_agent_credentials' / hashlib.sha256(database.encode()).hexdigest()


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Invalid credential storage permissions.')


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Invalid credential storage permissions.')
        value = stream.read(16385)
        if len(value) > 16384:
            raise ValueError('Invalid credential size.')
        return value


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _key(root):
    path = root / 'key'
    if not path.exists():
        # Write fully before publishing the key, including concurrent workers.
        temporary = root / ('.key-' + uuid.uuid4().hex)
        try:
            _write(temporary, Fernet.generate_key())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    return _read(path)


def _filename(reference):
    if not re.fullmatch(PREFIX + '[A-F0-9]{32}', reference):
        raise ValueError('Invalid runtime credential reference.')
    return reference + '.bin'


def store(bundle, data_dir=None):
    root = _root(bundle['database'], data_dir)
    _private_directory(root.parent)
    _private_directory(root)
    reference = PREFIX + uuid.uuid4().hex.upper()
    encrypted = Fernet(_key(root)).encrypt(json.dumps(bundle).encode())
    _write(root / _filename(reference), encrypted)
    return reference


def load(reference, database, data_dir=None):
    root = _root(database, data_dir)
    value = Fernet(_read(root / 'key')).decrypt(_read(root / _filename(reference)))
    return value.decode()


def remove(reference, database, data_dir=None):
    (_root(database, data_dir) / _filename(reference)).unlink(missing_ok=True)


def local_keys():
    """Read only the deployment-selected local profile, never a UI-supplied path."""
    import shlex
    path = Path(os.environ.get('AI_AGENT_LOCAL_ENV_FILE', '/mnt/agent/profiles/odoo-internal/.env'))
    values = {}
    for line in _read(path).decode().splitlines():
        name, separator, value = line.partition('=')
        if separator and name in ('API_SERVER_KEY', 'HERMES_DASHBOARD_SESSION_TOKEN'):
            tokens = shlex.split(value)
            if len(tokens) == 1:
                values[name] = tokens[0]
    if not all(values.get(k) for k in ('API_SERVER_KEY', 'HERMES_DASHBOARD_SESSION_TOKEN')):
        raise ValueError('Local credentials unavailable.')
    return values
