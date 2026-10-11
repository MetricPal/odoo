from .adapter import SlackAdapter
from odoo.addons.omni_channel.providers.base import register_adapter
register_adapter('slack', SlackAdapter, module='omni_slack')
