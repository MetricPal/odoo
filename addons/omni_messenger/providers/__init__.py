from . import graph, webhook, adapter

from odoo.addons.omni_channel.providers.base import register_adapter

register_adapter('messenger', adapter.MessengerAdapter, module='omni_messenger')
