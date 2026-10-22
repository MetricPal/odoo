{
    'name': 'Messaging Marketing',
    'version': '20.0.1.1.0',
    'category': 'Marketing/Messaging Marketing',
    'summary': 'Send approved marketing messages on WhatsApp and Telegram to people who opted in',
    'description': 'Marketing campaigns over messaging channels connected in Omnichannel: contacts with '
                   'recorded opt-in per channel, lists, opt-out and blacklist, mailings reviewed in Approval '
                   'Center before anything is sent, and delivery statistics.',
    'author': 'metric.io',
    'license': 'LGPL-3',
    'depends': ['omni_channel', 'approval_center', 'phone_validation', 'utm', 'link_tracker'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'views/contact_views.xml',
        'views/mailing_views.xml',
        'views/trace_views.xml',
        'views/approval_views.xml',
        'views/inbox_views.xml',
        'wizard/consent_wizard_views.xml',
        'views/menus.xml',
        'data/cron.xml',
    ],
    'assets': {
        'web.assets_backend': ['messaging_marketing/static/src/mailing.scss'],
    },
    'icon': '/messaging_marketing/static/description/icon.svg',
    'application': True,
    'installable': True,
}
