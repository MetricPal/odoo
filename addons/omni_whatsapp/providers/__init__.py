from . import connection, webhook, adapter

from odoo.addons.omni_channel.providers.base import register_adapter

register_adapter('whatsapp', adapter.WhatsAppAdapter, module='omni_whatsapp')
