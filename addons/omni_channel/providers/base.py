"""Trusted addon registry. Never resolve Python code from database input."""

from dataclasses import dataclass
from types import MappingProxyType


class AdapterUnavailable(Exception):
    pass


@dataclass(frozen=True)
class HealthResult:
    healthy: bool
    namespace: str = ''
    account_key: str = ''
    sender_key: str = ''


_ADAPTERS = {}
_ADAPTER_MODULES = {}


def register_adapter(key, factory, *, module=None):
    if key in _ADAPTERS:
        raise ValueError(f'Adapter already registered: {key}')
    _ADAPTERS[key] = factory
    if module:
        _ADAPTER_MODULES[key] = module


def get_adapter(key):
    factory = _ADAPTERS.get(key)
    if factory is None:
        raise AdapterUnavailable(key)
    return factory()


def installed_adapters(env=None):
    """Loaded Python factories, optionally restricted to this database's addons.

    Never unregister globally on uninstall: another database in this process
    can still depend on the same factory. Unowned factories support core mocks.
    """
    if env is None:
        return MappingProxyType(_ADAPTERS)
    installed = set(env['ir.module.module'].sudo().search([
        ('name', 'in', list(_ADAPTER_MODULES.values())),
        ('state', 'in', ['installed', 'to upgrade']),
    ]).mapped('name'))
    return MappingProxyType({
        key: factory for key, factory in _ADAPTERS.items()
        if key not in _ADAPTER_MODULES or _ADAPTER_MODULES[key] in installed
    })
