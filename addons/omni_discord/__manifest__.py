{
    "name": "Omnichannel Discord",
    "version": "20.0.1.0.0",
    "summary": "Receive Discord DMs and chosen server channels in the shared inbox; send approved replies",
    "description": "Connect a Discord bot to Omnichannel. A small relay program (tools/discord_relay.py) holds "
                   "Discord's gateway connection and forwards new messages to Odoo, signed. Replies are reviewed "
                   "and approved, then sent by Odoo through Discord's API.",
    "category": "Productivity",
    "author": "metric.io",
    "license": "LGPL-3",
    "icon": "/omni_discord/static/description/icon.svg",
    "depends": ["omni_channel"],
    "external_dependencies": {"python": ["requests", "cryptography"]},
    "data": ["views/discord_views.xml"],
    "assets": {"web.assets_backend": ["omni_discord/static/src/discord.js", "omni_discord/static/src/discord.xml"]},
    "installable": True,
    "application": False,
}
