{
    'name': 'Mentions',
    'version': '1.0',
    'category': 'Productivity/Discuss',
    'summary': 'Mentions in activities, SMS, Omnichannel and social reach the user, grouped per template and day',
    'author': 'metric.io',
    'depends': ['mail'],
    'data': [
        'security/ir.access.csv',
        'data/ir_cron.xml',
        'views/metric_mention_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
