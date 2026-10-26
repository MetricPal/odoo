{
    'name': 'Marketing: consent and preferences',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'One consent record per person and channel, a preference page, and approved data requests',
    'description': 'A consent ledger for email, SMS, WhatsApp, Telegram and social messages: every opt-in and '
                   'opt-out with its source and evidence, kept in sync with Messaging consents and the email and '
                   'phone blacklists. People manage their own channels and topics on a preference page. Requests '
                   'for a copy or erasure of a person\'s marketing data go through approval.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'mass_mailing_sms', 'messaging_marketing', 'approval_center'],
    'data': [
        'security/ir.access.csv',
        'security/security.xml',
        'data/approval.xml',
        'data/topics.xml',
        'views/consent_views.xml',
        'views/preference_templates.xml',
    ],
    'post_init_hook': '_backfill',
    'auto_install': True,
    'icon': '/marketing_intel_consent/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
