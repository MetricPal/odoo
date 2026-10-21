from . import models, providers


def uninstall_hook(env):
    env['omni.social.connection'].sudo().with_context(active_test=False).search(
        [('provider', '=', 'facebook')])._retire_provider()
