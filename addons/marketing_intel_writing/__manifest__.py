{
    'name': 'Marketing: writing tools',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Rewrite, shorten, translate and fit texts to their channel with the marketing assistant',
    'description': 'Writing tools on every marketing text: email subject, preview text and body, SMS, Messaging '
                   '(WhatsApp, Telegram), social posts and campaign texts. Rewrite, Shorter, Longer, Tone, '
                   'Translate, Fix grammar, Hashtags, Subject lines (with the standard A/B test), Fit to the channel and '
                   'Ask something else. The marketing assistant answers with a suggestion beside the text; nothing '
                   'changes until you click Use, and the usual reviews still apply.',
    'author': 'metric.io',
    'depends': ['marketing_intel_ai', 'marketing_intel_team', 'mass_mailing_sms', 'messaging_marketing', 'omni_social'],
    'data': [
        'views/writing_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_writing/static/src/writing_client.js',
            'marketing_intel_writing/static/src/writing_tools.*',
            'marketing_intel_writing/static/src/editor/*',
        ],
        'mass_mailing.assets_builder': [
            'marketing_intel_writing/static/src/builder/*',
        ],
        'web.assets_unit_tests': [
            'marketing_intel_writing/static/tests/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
