{
    'name': 'AI Home',
    'version': '1.6',
    'category': 'Productivity',
    'summary': 'Home: my plan, decisions waiting for me, what others did, and the assistant',
    'author': 'metric.io',
    'icon': '/ai_home/static/description/icon.svg',
    'depends': ['web', 'mail', 'website'],
    'data': [
        'security/ir.access.csv',
        'security/ai_home_security.xml',
        'views/ai_home_views.xml',
        'views/ai_home_source_views.xml',
        'data/ai_home_sources.xml',
        # 'views/website_templates.xml',
    ],
    'demo': [
        'demo/ai_home_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_home/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'ai_home/static/tests/**/*',
        ],
    },
    'auto_install': True,
    'application': True,
    'license': 'LGPL-3',
    'installable': True,
}
