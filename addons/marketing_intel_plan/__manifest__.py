{
    'name': 'Marketing: campaigns',
    'version': '20.0.1.1.0',
    'category': 'Marketing',
    'summary': 'Campaigns with drafts in Social, Messaging, Email, SMS and Events, results and goals',
    'description': 'Create campaigns by hand or from a suggestion. Drafts are prepared in each app (with your permissions, each under its own approval); results are read back and count towards your goals.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'utm'],
    'data': [
        'security/ir.access.csv',
        'security/security.xml',
        'views/plan_views.xml',
        'data/cron.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_plan/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
