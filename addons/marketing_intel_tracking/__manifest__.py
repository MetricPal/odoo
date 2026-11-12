{
    'name': 'Marketing: campaign tracking and results by channel',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'UTM on every marketing tool, and the panel\'s results by channel and source',
    'description': 'Every marketing tool tags its links with a UTM campaign, medium and source: Email and SMS '
                   'Marketing (Odoo), Messaging Marketing (WhatsApp, Telegram) and Social posts (Social Marketing: '
                   'campaign tracking, installed with this module). The medium and the source say which channel '
                   'and which mailing or platform a click came from, so no tool shows them and people choose only '
                   'the campaign; Marketing users see it in Email and SMS Marketing without Odoo\'s Mailing '
                   'Campaigns option. The Marketing panel gets a Results by channel and source '
                   'block: clicks, leads, won deals, revenue and spend per channel and per mailing or platform, with a '
                   'donut chart; every number opens its list.',
    'author': 'metric.io',
    'depends': ['marketing_intel_team', 'mass_mailing_sms', 'messaging_marketing', 'social_utm'],
    'data': [
        'views/tracking_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_tracking/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'marketing_intel_tracking/static/tests/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
