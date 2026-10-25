"""The campaign approval releases the campaign; refusals send it back to Content."""

from odoo import _, models


class Request(models.Model):
    _inherit = 'approval.center.request'

    def action_approve(self):
        result = super().action_approve()
        for request in self.sudo():
            if request.target_model == 'mi.plan' and request.state == 'approved' and not request.executed_at:
                # The approval is the authorization; the release runs as the person who asked for it.
                request.with_user(request.requester_id).sudo().action_execute()
            elif request.state == 'approved':
                self._mi_plans_of(request)._sync_state()
        return result

    def action_refuse(self):
        result = super().action_refuse()
        for request in self.sudo():
            plans = self._mi_plans_of(request)
            if request.state == 'refused':
                plans._back_to_content(_('“%(request)s” was refused by %(user)s. Edit and send for review again.',
                                         request=request.name, user=self.env.user.name))
        return result

    def _mi_plans_of(self, request):
        """Campaigns the request belongs to: the campaign request itself or a channel's own approval."""
        Plan = self.env['mi.plan'].sudo()
        if request.target_model == 'mi.plan':
            return Plan.browse(request.target_res_id).exists()
        items = self.env['mi.plan.item'].sudo().search([('res_model', '=', request.target_model),
                                                         ('res_id', '=', request.target_res_id)])
        if not items and 'social_publication_id' in request._fields and request.social_publication_id:
            campaign = request.social_publication_id.campaign_id
            items = self.env['mi.plan.item'].sudo().search([('res_model', '=', 'omni.social.campaign'),
                                                             ('res_id', '=', campaign.id)])
        return items.plan_id
