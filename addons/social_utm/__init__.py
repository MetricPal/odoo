from . import models

from odoo.addons.omni_social.models.social import internal


def _post_init_hook(env):
    """Campaigns created before this module get their tracking campaign too."""
    Campaign = env['omni.social.campaign'].with_context(active_test=False)
    for campaign in Campaign.search([('utm_campaign_id', '=', False)]):
        internal(campaign.sudo()).write({'utm_campaign_id': env['utm.campaign'].create({'title': campaign.name}).id})
    for campaign in Campaign.search([('utm_campaign_id', '!=', False)]):
        internal(campaign.publication_ids.filtered(lambda p: not p.utm_campaign_id).sudo()).write(
            {'utm_campaign_id': campaign.utm_campaign_id.id})
