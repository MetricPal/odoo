{
    "name": "Omnichannel Slack", "version": "20.0.1.0.0",
    "summary": "Receive Slack direct messages in the shared Odoo inbox",
    "description": "Connect a Slack app, receive private text messages and send human-approved replies. Channel messages, attachments and unsupervised sending are not supported in this release.",
    "category": "Productivity", "author": "metric.io", "license": "LGPL-3",
    "icon": "/omni_slack/static/description/icon.svg",
    "depends": ["omni_channel"], "external_dependencies": {"python": ["requests", "cryptography"]},
    "data": ["views/setup.xml"],
    "assets": {"web.assets_backend": ["omni_slack/static/src/setup.js", "omni_slack/static/src/setup.xml"]},
    "installable": True, "application": False,
}
