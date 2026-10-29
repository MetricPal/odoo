"""Every campaign gets its three pillars (Awareness, Consideration, Conversion) with dates and budget shares."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['mi.plan'].with_context(active_test=False, tracking_disable=True).search([])._ensure_pillars()
