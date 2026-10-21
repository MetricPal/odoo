{
    'name': 'Omnichannel: AI reply drafts',
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Draft an inbox reply with an AI Agent; it is still edited and approved before sending',
    'depends': ['omni_channel', 'ai_agent'],
    'data': [
        'security/ir.access.csv',
        'views/command_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
