{
    "name": "Omnichannel Messenger",
    "version": "20.0.1.0.0",
    "summary": "Receive Facebook Page messages in the shared inbox and send approved replies",
    "description": "Connect a Facebook Page to Omnichannel. Private text messages arrive in the inbox through a "
                   "signed webhook; replies are reviewed and approved like other channels and are sent only "
                   "within 24 hours of the person's last message.",
    "category": "Productivity",
    "author": "metric.io",
    "license": "LGPL-3",
    "icon": "/omni_messenger/static/description/icon.svg",
    "depends": ["omni_channel"],
    "external_dependencies": {"python": ["requests", "cryptography"]},
    "data": ["views/messenger_views.xml"],
    "assets": {"web.assets_backend": ["omni_messenger/static/src/messenger.js", "omni_messenger/static/src/messenger.xml"]},
    "installable": True,
    "application": False,
}
