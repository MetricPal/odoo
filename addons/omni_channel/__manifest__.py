{
    'name': 'Omni-Channel',
    'version': '20.0.1.0.0',
    'summary': 'Manage communication channels, sender readiness and ownership in one governed workspace',
    'category': 'Productivity',
    'author': 'metric.io',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'bus', 'web', 'approval_center'],
    'data': [
        'security/omni_security.xml',
        'security/ir.access.csv',
        'data/catalog.xml',
        'views/omni_views.xml',
    ],
    'assets': {'web.assets_backend': ['omni_channel/static/src/scss/omni.scss']},
    'icon': '/omni_channel/static/description/icon.svg',
    'application': True,
    'installable': True,
}
