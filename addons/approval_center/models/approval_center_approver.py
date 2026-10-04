from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ApprovalCenterApprover(models.Model):
    _name = 'approval.center.approver'
    _description = 'Approval Center Approver'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        'approval.center.policy',
        string='Category',
        ondelete='cascade',
        index=True,
    )
    request_id = fields.Many2one(
        'approval.center.request',
        string='Request',
        ondelete='cascade',
        index=True,
    )
    user_id = fields.Many2one('res.users', required=True)
    required = fields.Boolean(default=False)
    status = fields.Selection([
        ('new', 'New'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], default='new', required=True)

    @api.constrains('category_id', 'request_id', 'user_id')
    def _check_unique_approver_scope(self):
        for approver in self:
            if bool(approver.category_id) == bool(approver.request_id):
                raise ValidationError(_('An approver line must belong to one approval type or one approval request.'))
            domain = [('user_id', '=', approver.user_id.id), ('id', '!=', approver.id)]
            if approver.category_id:
                domain.append(('category_id', '=', approver.category_id.id))
                message = _('The same approver cannot be added twice to the same approval type.')
            else:
                domain.append(('request_id', '=', approver.request_id.id))
                message = _('The same approver cannot be added twice to the same approval request.')
            if self.search_count(domain):
                raise ValidationError(message)
