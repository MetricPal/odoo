"""Factories come only from installed addon code."""

from .capabilities import Capabilities
from . import http

_FACTORIES = {}
_CAPABILITIES = {}


def register(name, factory, capabilities=None):
    if name in _FACTORIES:
        raise ValueError('Duplicate social provider')
    caps = capabilities or getattr(factory, 'CAPABILITIES', None) or Capabilities(label=name.title())
    _FACTORIES[name] = factory
    _CAPABILITIES[name] = caps
    http.allow_hosts(*caps.hosts)
    if caps.oauth:
        from urllib.parse import urlsplit

        http.allow_hosts(urlsplit(caps.oauth.token_url).hostname)


def _installed(env, name):
    return bool(
        env['ir.module.module'].sudo().search_count(
            [('name', '=', 'omni_' + name), ('state', 'in', ['installed', 'to upgrade'])]
        )
    )


def provider(env, name):
    if name not in _FACTORIES or not _installed(env, name):
        raise ValueError('Provider addon unavailable')
    return _FACTORIES[name]()


def capabilities(name):
    """Declared rules for a platform, or None when no connector registered it."""
    return _CAPABILITIES.get(name)


def installed(env):
    """Names of the social connectors installed in this database, in a stable order."""
    names = sorted(_FACTORIES)
    if not names:
        return []
    found = set(
        env['ir.module.module'].sudo().search(
            [('name', 'in', ['omni_' + n for n in names]), ('state', 'in', ['installed', 'to upgrade'])]
        ).mapped('name')
    )
    return [n for n in names if 'omni_' + n in found]
