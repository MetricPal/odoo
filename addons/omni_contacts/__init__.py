from . import models


def _post_init_hook(env):
    """Contacts already linked to Omnichannel chats get their channels right away."""
    identities = env['omni.identity'].sudo().search([('partner_id', '!=', False)])
    env['omni.partner.channel']._sync_identities(identities)
