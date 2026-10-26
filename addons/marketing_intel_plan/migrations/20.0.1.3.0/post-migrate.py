"""Next steps become Odoo activities: create them for campaigns that are already running."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env['mi.plan'].search([('is_template', '=', False),
                                   ('state', 'in', ('brief', 'content', 'review', 'scheduled', 'live'))])
    plans._sync_owner_activity()
