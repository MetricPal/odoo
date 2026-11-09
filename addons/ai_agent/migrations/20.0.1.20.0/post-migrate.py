from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Departments (and companies) that already have a Hermes profile get their AI assistant user (owner, 2026-11-09:
    made automatically with the profile)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ai.agent.profile'].with_context(active_test=False).search([])._ensure_assistant_users()
