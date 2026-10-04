from odoo import fields, models


class ApprovalCenterAudit(models.Model):
    _name = 'approval.center.audit'
    _description = 'Approval Audit'
    _order = 'create_date desc, id desc'
    _log_access = True

    request_id = fields.Many2one(
        'approval.center.request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    policy_id = fields.Many2one(
        related='request_id.policy_id',
        string='Category',
        store=True,
        readonly=True,
    )
    actor_id = fields.Many2one(
        'res.users',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    event = fields.Selection([
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('blocked', 'Blocked'),
        ('executed', 'Executed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], required=True, readonly=True)
    target_model = fields.Char(related='request_id.target_model', store=True, readonly=True)
    target_res_id = fields.Integer(related='request_id.target_res_id', store=True, readonly=True)
    action_name = fields.Char(related='request_id.action_name', store=True, readonly=True)
    message = fields.Text(readonly=True)
    result = fields.Text(readonly=True)
