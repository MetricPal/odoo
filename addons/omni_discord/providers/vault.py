"""Encrypted bot credentials; Odoo records keep only an opaque reference."""
from odoo.addons.omni_channel.providers.vault import CredentialVault

_VAULT = CredentialVault("OMNI_SECRET_DISCORD_", "omni_discord_credentials", ("bot_id",))


def store(bundle, data_dir=None):
    return _VAULT.store(bundle, data_dir)


def load(reference, *, database, company_id, purpose_id, bot_id, data_dir=None):
    return _VAULT.load(reference, database=database, company_id=company_id, purpose_id=purpose_id,
                       data_dir=data_dir, bot_id=bot_id)


def remove(reference, database, data_dir=None):
    return _VAULT.remove(reference, database, data_dir)
