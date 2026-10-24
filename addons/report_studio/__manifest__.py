{
    'name': 'Report Studio',
    'version': '20.0.2.0.0',
    'category': 'Productivity',
    'summary': 'Reports page in Dashboards: boxes on a 4-column page, A4/A3/Letter…, export PDF, Excel, PowerPoint, Word, HTML',
    'description': 'The Reports page of the Dashboards app: boxes (title, text, number, chart, table, list, image, '
                   'link, view from any app) on a 4-column page of the chosen size. Add views from any list, graph '
                   'or pivot. Export to PDF, Excel, PowerPoint, Word or HTML with the same layout. Numbers always '
                   'come from queries run with your access rights.',
    'author': 'metric.io',
    'depends': ['web', 'mail', 'spreadsheet_dashboard'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'report/report.xml',
        'views/report_views.xml',
    ],
    'application': False,
    'assets': {
        'web.assets_backend': [
            'report_studio/static/src/**/*.scss',
            'report_studio/static/src/**/*.js',
            'report_studio/static/src/**/*.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
}
