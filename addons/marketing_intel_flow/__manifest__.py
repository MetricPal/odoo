{
    'name': 'Marketing: workflows',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'When this happens, do that: approved once, then automatic (comments, DMs, events, clicks, leads)',
    'description': 'Simple marketing workflows built from cards: a trigger (a comment or private message on social '
                   'media, an event registration, an email click, a new lead) and steps (a WhatsApp or Telegram '
                   'message to opted-in contacts, add to a list, create a lead, a to-do). A manager approves the '
                   'workflow and its message once; then it runs on its own within limits, every run logged.',
    'author': 'metric.io',
    'depends': ['marketing_intel_plan', 'messaging_marketing', 'omni_social'],
    'data': [
        'security/ir.access.csv',
        'security/security.xml',
        'data/recipes.xml',
        'data/cron.xml',
        'views/flow_views.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_flow/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
