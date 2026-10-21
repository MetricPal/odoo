"""Encrypted private files. Odoo records contain only opaque references.

Thin wrapper over the shared Omnichannel vault; see its module docstring for
the key options (``OMNI_VAULT_KEY``).
"""
try:
    from odoo.addons.omni_channel.providers.vault import CredentialVault
except ImportError:  # loaded by path in the stand-alone protocol tests
    import importlib.util
    from pathlib import Path

    _spec = importlib.util.spec_from_file_location(
        "omni_channel_vault", Path(__file__).resolve().parents[2] / "omni_channel" / "providers" / "vault.py")
    _shared = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_shared)
    CredentialVault = _shared.CredentialVault

_VAULT = CredentialVault("OMNI_SECRET_SOCIAL_", "omni_social_credentials", ("provider", "account_key"))
PREFIX = _VAULT.prefix
_root = _VAULT._root
_file = _VAULT._file


def store(bundle, data_dir=None):
    return _VAULT.store(bundle, data_dir)


def load(reference, *, database, company_id, purpose_id, provider, account_key, data_dir=None):
    return _VAULT.load(reference, database=database, company_id=company_id, purpose_id=purpose_id,
                       data_dir=data_dir, provider=provider, account_key=account_key)


def remove(reference, database, data_dir=None):
    return _VAULT.remove(reference, database, data_dir)
