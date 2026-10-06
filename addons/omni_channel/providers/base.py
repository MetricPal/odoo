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


def register_adapter(key, factory):
    if key in _ADAPTERS:
        raise ValueError(f'Adapter already registered: {key}')
    _ADAPTERS[key] = factory


def get_adapter(key):
    factory = _ADAPTERS.get(key)
    if factory is None:
        raise AdapterUnavailable(key)
    return factory()


def installed_adapters():
    return MappingProxyType(_ADAPTERS)
