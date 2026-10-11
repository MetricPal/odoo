{
    'name': 'Omnichannel Templates',
    'version': '20.0.1.1.0',
    'summary': 'Reusable channel content with record fields and a safe live preview',
    'author': 'metric.io', 'category': 'Productivity', 'license': 'LGPL-3',
    'depends': ['omni_channel'],
    'data': ['security/ir.access.csv', 'security/access.xml', 'views/templates.xml'],
    'assets': {'web.assets_backend': [
        'omni_template/static/src/editor.js',
        'omni_template/static/src/editor.xml',
        'omni_template/static/src/editor.scss',
    ]},
    'icon': '/omni_template/static/description/icon.svg',
    'application': False, 'installable': True,
}
