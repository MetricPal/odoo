{
    'name': 'Approval Center',
    'version': '20.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Review, approve, and audit supervised business actions',
    'description': """
Approval Center gives teams one governed place to review business actions,
approve or reject them, and execute approved work through Odoo actions with an
audit trail.
""",
    'author': 'metric.io',
    'icon': '/approval_center/static/description/icon.svg',
    'depends': [
        'base',
        'hr',
        'mail',
    ],
    'data': [
        'security/approval_center_security.xml',
        'security/ir.access.csv',
        'data/approval_center_data.xml',
        'views/approval_center_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'approval_center/static/src/scss/approval_center.scss',
        ],
    },
    'application': True,
    'license': 'LGPL-3',
    'installable': True,
}
