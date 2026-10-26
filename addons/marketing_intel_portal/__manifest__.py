{
    'name': 'Marketing: client portal',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Client contacts follow their brand\'s campaigns and results, file requests, sign off campaigns and proofs',
    'description': 'For agencies and advisors: a client contact with portal access sees only the brands they are '
                   'added to: campaigns with progress and results per channel, proofs to review, and their '
                   'requests. Where the brand allows it, the client signs off a campaign before the internal '
                   'review, and approves proofs or asks for changes; every decision is written on the campaign.',
    'author': 'metric.io',
    'depends': ['marketing_intel_work', 'portal'],
    'data': [
        'data/portal_entry.xml',
        'views/client_views.xml',
        'views/portal_templates.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_portal/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
