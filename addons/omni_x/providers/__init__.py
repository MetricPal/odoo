from .api import Adapter
from odoo.addons.omni_social.providers.registry import register

register('x', Adapter)
