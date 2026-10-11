from .adapter import TeamsAdapter
from odoo.addons.omni_channel.providers.base import register_adapter
register_adapter('teams', TeamsAdapter, module='omni_teams')
