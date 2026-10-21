"""Factories come only from installed addon code."""

_FACTORIES = {}


def register(name, factory):
    if name in _FACTORIES:
        raise ValueError('Duplicate social provider')
    _FACTORIES[name] = factory


def provider(env, name):
    if name not in _FACTORIES or not env['ir.module.module'].sudo().search_count(
        [('name', '=', 'omni_' + name), ('state', 'in', ['installed', 'to upgrade'])]
    ):
        raise ValueError('Provider addon unavailable')
    return _FACTORIES[name]()
