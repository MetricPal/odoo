"""The marketing manager's control panel view starts with the management view (CRM and UTM figures)."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    layout = env['mi.panel.layout'].search([('role', '=', 'manager'), ('user_id', '=', False)], limit=1)
    if layout and not any(block.get('key') == 'management' for block in layout.blocks or []):
        layout.blocks = [{'key': 'management', 'width': 'full'}] + list(layout.blocks or [])
