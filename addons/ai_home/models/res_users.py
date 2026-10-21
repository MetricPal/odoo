import json

from odoo import fields, models

FAVORITE_LIMIT = 12


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Menu ids of the user's Home favorites, in display order (JSON list).
    # Read and written only through ai.home.item for the current user.
    ai_home_favorites = fields.Char(copy=False, groups='base.group_system')

    def _ai_home_favorite_ids(self):
        self.ensure_one()
        try:
            value = json.loads(self.sudo().ai_home_favorites or 'null')
        except ValueError:
            return None
        if not isinstance(value, list):
            return None
        return [item if isinstance(item, int) else None for item in value][:FAVORITE_LIMIT]
