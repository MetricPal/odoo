{
    'name': 'Marketing Intelligence: campaign plans',
    'version': '20.0.1.1.0',
    'category': 'Marketing',
    'summary': 'Turn a chosen campaign option into linked drafts in Social, Messaging, Email, SMS and Events',
    'description': 'A campaign plan creates one tracking campaign and a draft in each marketing app the option '
                   'uses. Drafts are created with your permissions and still need their own approval; nothing is '
                   'sent from Marketing Intelligence. Includes a marketing calendar with overlap warnings, '
                   'results per plan (sends, clicks, leads, won deals, revenue, registrations), targets vs actual and '
                   'lessons learned that feed the next analysis.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'utm'],
    'data': [
        'security/ir.access.csv',
        'security/security.xml',
        'views/plan_views.xml',
        'data/cron.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
