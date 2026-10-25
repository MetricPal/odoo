{
    'name': 'AI Home',
    'version': '1.4',
    'category': 'Productivity',
    'summary': 'AI Home: my work, items needing attention, automations, workflow runs and recent activity',
    'author': 'metric.io',
    'icon': '/ai_home/static/description/icon.svg',
    'depends': ['web', 'website'],
    'data': [
        'security/ir.access.csv',
        'security/ai_home_security.xml',
        'views/ai_home_views.xml',
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
