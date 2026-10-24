{
    'name': 'Report Studio',
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Build readable reports from Odoo data; preview in HTML, export PDF, Excel, PowerPoint or Word',
    'description': 'A report is a list of blocks (headings, text, KPI tiles, tables) over any model you can read. '
                   'The HTML preview is the single source; PDF, XLSX, PPTX and DOCX are rendered from the same '
                   'blocks. Numbers always come from queries run with your access rights.',
    'author': 'metric.io',
    'depends': ['web', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'report/report.xml',
        'views/report_views.xml',
    ],
    'application': True,
    'license': 'LGPL-3',
    'installable': True,
}
