"""A workflow starts when its approval is approved, and goes back to draft when it is refused."""

from odoo import models


class Request(models.Model):
    _inherit = 'approval.center.request'

    def action_approve(self):
        result = super().action_approve()
        for request in self.sudo().filtered(lambda r: r.target_model == 'mi.flow' and r.state == 'approved'):
            flow = self.env['mi.flow'].sudo().browse(request.target_res_id).exists()
            if flow.approval_request_id == request:
                flow._on_approved()
        return result

    def action_refuse(self):
        result = super().action_refuse()
        for request in self.sudo().filtered(lambda r: r.target_model == 'mi.flow' and r.state == 'refused'):
            flow = self.env['mi.flow'].sudo().browse(request.target_res_id).exists()
            if flow.approval_request_id == request:
                flow._on_refused()
        return result
