{
    'name': 'Social Marketing: AI drafts',
    'version': '20.0.1.0.0',
    'category': 'Marketing/Social Marketing',
    'summary': 'Draft posts and replies, adapt them to each platform and summarize activity with an AI Agent',
    'description': 'AI writes drafts and suggestions only. Every post and reply is still edited by a person '
                   'and approved in Approval Center before it is published.',
    'author': 'metric.io',
    'depends': ['omni_social', 'ai_agent'],
    'data': [
        'security/ir.access.csv',
        'security/access.xml',
        'views/social_ai_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
