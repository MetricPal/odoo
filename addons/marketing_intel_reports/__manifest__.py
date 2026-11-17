{
    'name': 'Marketing: reports',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Reports under Insights: Executive overview, Channel performance, Funnel and attribution, Audience',
    'description': 'The Reports section of Insights. Its four pages (Executive overview, Channel performance, '
                   'Funnel and attribution, Audience) open from the menu; the section itself has no page. '
                   'The pages are added one by one, each from an approved mock.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'marketing_intel_plan'],
    'data': [
        'views/report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_reports/static/src/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
