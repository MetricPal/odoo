from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Profiles made before the Tools and services tab: list every offered Hermes tool (off, as Hermes has them) and
    the ERP's own tool server."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ai.agent.profile'].with_context(active_test=False).search([])._ensure_tools()
