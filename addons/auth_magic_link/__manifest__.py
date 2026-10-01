{
    "name": "Magic Link Authentication",
    "summary": "Passwordless Magic Link authentication for Odoo 20 Community",
    "version": "20.0.1.0.0",
    "category": "Administration/Users",
    "license": "LGPL-3",
    "author": "Odoo Community",
    "depends": ["web", "website", "mail", "base_setup", "auth_oauth"],
    "data": [
        "security/ir.access.csv",
        "data/mail_template.xml",
        "data/authentication_settings.xml",
        "data/ir_cron.xml",
        "views/res_config_settings_views.xml",
        "views/login_templates.xml",
    ],
    "assets": {
        "web.assets_frontend_minimal": [
            "auth_magic_link/static/src/js/user_switch_magic_link.js",
            "auth_magic_link/static/src/scss/auth_magic_link.scss",
            "auth_magic_link/static/src/scss/auth_email_link.scss",
        ],
        "web.assets_backend": [
            "auth_magic_link/static/src/js/auth_login_method_radio.js",
            "auth_magic_link/static/src/xml/auth_login_method_radio.xml",
        ],
    },
    "installable": True,
    "application": False,
}
