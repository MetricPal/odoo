{
 "name": "Omnichannel Microsoft Teams", "version": "20.0.1.0.0",
 "summary": "Receive Teams personal chats and send approved replies in Odoo",
 "description": "Connect a single-tenant Teams bot to the shared Omnichannel inbox. Receive private text, send a confirmed setup test and reply through human approval. Group chats, channels and attachments are not supported.",
 "category": "Productivity", "author": "metric.io", "license": "LGPL-3",
 "icon": "/omni_teams/static/description/icon.svg",
 "depends": ["omni_channel"], "external_dependencies": {"python": ["requests","cryptography"]},
 "data": ["data/catalog.xml","views/setup.xml"],
 "assets": {"web.assets_backend": ["omni_teams/static/src/setup.js","omni_teams/static/src/setup.xml"]},
 "installable": True, "application": False,
}
