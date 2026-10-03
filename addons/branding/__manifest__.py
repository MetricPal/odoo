{
    'name': 'metric.io Branding',
    'version': '20.0.1.1.0',
    'category': 'Hidden',
    'summary': 'Apply the metric.io identity to company, website, and authentication emails',
    'author': 'metric.io',
    'icon': '/branding/static/src/img/metric_io_favicon.png',
    'depends': ['auth_signup', 'digest', 'website'],
    'data': [
        'data/res_company_data.xml',
        'data/website_data.xml',
        'views/auth_signup_templates_email.xml',
        'views/digest_templates.xml',
        'views/mail_templates.xml',
        'data/mail_template_data.xml',
        'views/portal_templates.xml',
        'views/res_config_settings_views.xml',
        'views/webclient_templates.xml',
        'views/website_template.xml'
    ],
    'post_init_hook': '_post_init_hook',
    'assets': {
        'web.assets_backend': [
            'after',
            'web/static/src/webclient/user_menu/user_menu_items.js',
            'branding/static/src/scss/navbar.scss',
            'branding/static/src/xml/navbar.xml',
            "branding/static/src/js/user_menu.js",
            "branding/static/src/scss/apps_menu.scss",
            'branding/static/src/xml/apps_menu.xml',
            "branding/static/src/scss/user_menu.scss",
            'branding/static/src/xml/user_menu.xml'
        ],
        'web.assets_unit_tests': [
            'branding/static/tests/user_menu.test.js',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
