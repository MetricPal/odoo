from .telegram import TelegramAdapter
from odoo.addons.omni_channel.providers.base import register_adapter

register_adapter("telegram", TelegramAdapter, module="omni_telegram")
