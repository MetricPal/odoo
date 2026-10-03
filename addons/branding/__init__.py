from . import models


def _post_init_hook(env):
    env['mail.template'].sudo().search([
        ('email_layout_force_footer', '=', False),
    ]).write({'email_layout_force_footer': True})
