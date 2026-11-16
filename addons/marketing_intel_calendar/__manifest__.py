{
    'name': 'Marketing: content calendar',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Every email, SMS, message and social post on one calendar',
    'description': 'One calendar for what goes out to customers: emails and SMS (Email Marketing, SMS Marketing), '
                   'messages (Messaging Marketing) and social posts (Social), coloured by channel, with filters by '
                   'channel and campaign and the same content as a list. An item opens in its own app; dragging it '
                   'changes its time where its app allows that. Nothing is edited, reviewed or sent from the '
                   'calendar.',
    'author': 'metric.io',
    'depends': ['marketing_intel_plan', 'mass_mailing_sms', 'messaging_marketing', 'omni_social'],
    'data': [
        'security/ir.access.csv',
        'data/channels.xml',
        'views/content_views.xml',
    ],
    'demo': [
        'demo/calendar_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_calendar/static/src/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
