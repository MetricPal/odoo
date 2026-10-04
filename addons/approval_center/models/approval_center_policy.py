from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ApprovalCenterPolicy(models.Model):
    _name = 'approval.center.policy'
    _description = 'Approval Type'
    _inherit = ['mail.thread']
    _order = 'sequence, name, id'

    FIELD_VISIBILITY = [
        ('required', 'Required'),
        ('optional', 'Optional'),
        ('no', 'None'),
    ]

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    image_128 = fields.Image("Icon", max_width=128, max_height=128)
    approval_minimum = fields.Integer(
        string='Minimum Approval',
        default=1,
        required=True,
        tracking=True,
    )
    manager_approval = fields.Boolean(string="Employee's Manager", tracking=True)
    approver_sequence = fields.Boolean(string='Approvers Sequence?', tracking=True)
    approver_ids = fields.One2many(
        'approval.center.approver',
        'category_id',
        string='Approvers',
    )
    selected_approver_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_selected_approver_user_ids',
    )
    has_document = fields.Selection(FIELD_VISIBILITY, string='Document', default='optional', required=True)
    has_partner = fields.Selection(FIELD_VISIBILITY, string='Contact', default='no', required=True)
    has_date = fields.Selection(FIELD_VISIBILITY, string='Date', default='no', required=True)
    has_period = fields.Selection(FIELD_VISIBILITY, string='Period', default='no', required=True)
    has_items = fields.Selection(FIELD_VISIBILITY, string='Items', default='no', required=True)
    has_quantity = fields.Selection(FIELD_VISIBILITY, string='Quantity', default='no', required=True)
    has_amount = fields.Selection(FIELD_VISIBILITY, string='Amount', default='no', required=True)
    has_reference = fields.Selection(FIELD_VISIBILITY, string='Reference', default='no', required=True)
    has_payment = fields.Selection(FIELD_VISIBILITY, string='Payment', default='no', required=True)
    has_location = fields.Selection(FIELD_VISIBILITY, string='Location', default='no', required=True)
    request_count = fields.Integer(compute='_compute_request_counts')
    submitted_count = fields.Integer(string='To Review', compute='_compute_request_counts')
    model_id = fields.Many2one(
        'ir.model',
        string='Target Model',
        ondelete='cascade',
        tracking=True,
    )
    model = fields.Char(related='model_id.model', store=True, readonly=True)
    action_name = fields.Char(
        tracking=True,
        help='Public method to call on the target record after approval.',
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )

    @api.constrains('approval_minimum', 'manager_approval', 'approver_ids')
    def _check_approval_minimum(self):
        for category in self:
            if category.approval_minimum < 1:
                raise ValidationError(_('Minimum Approval must be at least 1.'))
            possible_approvers = len(category.approver_ids) + (1 if category.manager_approval else 0)
            if possible_approvers and category.approval_minimum > possible_approvers:
                raise ValidationError(_('Your minimum approval exceeds the total of default approvers.'))

    def _compute_request_counts(self):
        grouped = self.env['approval.center.request']._read_group(
            [('policy_id', 'in', self.ids)],
            ['policy_id', 'state'],
            ['__count'],
        )
        counts = {}
        submitted = {}
        for category, state, count in grouped:
            counts[category.id] = counts.get(category.id, 0) + count
            if state == 'submitted':
                submitted[category.id] = submitted.get(category.id, 0) + count
        for category in self:
            category.request_count = counts.get(category.id, 0)
            category.submitted_count = submitted.get(category.id, 0)

    @api.depends('approver_ids.user_id')
    def _compute_selected_approver_user_ids(self):
        for category in self:
            category.selected_approver_user_ids = category.approver_ids.user_id

    def action_new_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Approval Request'),
            'res_model': 'approval.center.request',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_policy_id': self.id},
        }

    def action_view_submitted_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Approval Requests'),
            'res_model': 'approval.center.request',
            'view_mode': 'kanban,list,form',
            'domain': [('policy_id', '=', self.id), ('state', '=', 'submitted')],
            'context': {'default_policy_id': self.id},
        }
