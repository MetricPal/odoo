{
    'name': 'Workflows',
    'summary': 'Build, test and monitor supervised business automations',
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'author': 'metric.io',
    'license': 'LGPL-3',
    'depends': ['base_automation', 'approval_center', 'web'],
    'data': ['security/security.xml', 'security/ir.access.csv',
             'views/workflow_views.xml', 'data/cron.xml'],
    'assets': {'web.assets_backend': [
        'workflow_center/static/src/workflows.js',
        'workflow_center/static/src/workflows.xml',
        'workflow_center/static/src/workflows.scss',
    ]},
    'application': True,
    'installable': True,
}
