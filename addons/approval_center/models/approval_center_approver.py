from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


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

    def _approval_trusted(self):
        # Delegate to the request model so integration capabilities apply here too.
        return self.env['approval.center.request']._approval_trusted()

    @api.model_create_multi
    def create(self, vals_list):
        if not self._approval_trusted():
            Request = self.env['approval.center.request']
            for vals in vals_list:
                request_id = vals.get('request_id') or self.env.context.get('default_request_id')
                if not request_id:
                    continue
                if vals.get('status', 'new') != 'new':
                    raise AccessError(_('Approver decisions are recorded with the Approve and Refuse buttons.'))
                request = Request.browse(request_id).exists()
                if request and request.sudo().state != 'to_submit':
                    raise UserError(_('Approvers are fixed once the request is submitted.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self._approval_trusted():
            request_lines = self.filtered('request_id')
            if 'status' in vals and request_lines:
                raise AccessError(_('Approver decisions are recorded with the Approve and Refuse buttons.'))
            if request_lines.sudo().request_id.filtered(lambda request: request.state != 'to_submit'):
                raise UserError(_('Approvers are fixed once the request is submitted.'))
            if vals.get('request_id'):
                target = self.env['approval.center.request'].sudo().browse(vals['request_id']).exists()
                if target and target.state != 'to_submit':
                    raise UserError(_('Approvers are fixed once the request is submitted.'))
        return super().write(vals)

    def unlink(self):
        if not self._approval_trusted() and self.sudo().request_id.filtered(lambda request: request.state != 'to_submit'):
            raise UserError(_('Approvers of a submitted request are kept for the audit trail.'))
        return super().unlink()

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
            if self.sudo().search_count(domain):
                raise ValidationError(message)
