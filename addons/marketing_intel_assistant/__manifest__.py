{
    'name': 'Marketing: assistant chat',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Tell the assistant what to do with campaigns and workflows; confirm; it goes through the usual reviews',
    'description': 'Write what you want ("create a Black Friday campaign for metric.io with email and social from '
                   '20 to 30 November", "how is the open day campaign doing?", "pause the comment workflow"). '
                   'Simple instructions are understood directly; others are read by your AI agent. The assistant '
                   'proposes exactly what it will do; nothing changes until you click Do it, it acts with your '
                   'own rights, and campaigns and workflows still need their usual review and approval.',
    'author': 'metric.io',
    'depends': ['marketing_intel_ai', 'marketing_intel_flow'],
    'data': [
        'security/ir.access.csv',
        'security/security.xml',
        'views/assistant_views.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_assistant/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
