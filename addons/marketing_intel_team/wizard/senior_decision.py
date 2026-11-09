from odoo import fields, models


class SeniorDecision(models.TransientModel):
    _name = 'mi.senior.decision'
    _description = 'Request changes in the senior review'

    plan_id = fields.Many2one('mi.plan', required=True)
    comment = fields.Text(string='What to change', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.plan_id._senior_request_changes(self.comment)
        return {'type': 'ir.actions.act_window_close'}
