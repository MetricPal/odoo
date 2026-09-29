{
    'name': 'metric.io Branding',
    'version': '1.0',
    'category': 'Hidden',
    'summary': 'Apply the metric.io identity to company, website, and authentication emails',
    'icon': '/branding/static/src/img/metric_io_favicon.png',
    'depends': ['auth_signup', 'digest', 'website'],
    'data': [
        'data/res_company_data.xml',
        'data/website_data.xml',
        'views/auth_signup_templates_email.xml',
        'views/digest_templates.xml',
        'views/mail_templates.xml',
        'views/portal_templates.xml',
        'views/webclient_templates.xml',
        'views/website_template.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'after',
            'web/static/src/webclient/user_menu/user_menu_items.js',
            'branding/static/src/user_menu/user_menu_items.js',
            'branding/static/src/scss/navbar.scss',
            'branding/static/src/xml/navbar.xml',
        ],
        'web.assets_unit_tests': [
            'branding/static/tests/user_menu.test.js',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
