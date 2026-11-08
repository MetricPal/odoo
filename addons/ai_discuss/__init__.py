from . import controllers, models


def _post_init(env):
    """Agents made before this module get their chat partner."""
    env['ai.agent'].with_context(active_test=False).search([])._ensure_partner()
