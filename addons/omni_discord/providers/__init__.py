from . import rest, relay, adapter

from odoo.addons.omni_channel.providers.base import register_adapter

register_adapter('discord', adapter.DiscordAdapter, module='omni_discord')
