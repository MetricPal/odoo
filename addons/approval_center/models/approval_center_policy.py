import re

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
        string='How many must approve',
        default=1,
        required=True,
        tracking=True,
        help='Number of approvals needed. Approvers marked "Must approve" are always needed on top of this count.',
    )
    manager_approval = fields.Boolean(
        string="Requester's manager approves", tracking=True,
        help="The manager set on the requester's employee record (Employees app) is added as the first approver.",
    )
    approver_sequence = fields.Boolean(
        string='Approve in order', tracking=True,
        help='Each approver can decide only after the previous ones have approved.',
    )
    allow_self_approval = fields.Boolean(
        string='Requester may approve own request',
        tracking=True,
        help='Let a requester who is also an approver decide on their own request. Off by default.',
    )
    setup_state = fields.Selection(
        [('ready', 'Ready'), ('needs_approvers', 'Needs approvers')],
        compute='_compute_setup_state', string='Setup',
        help='Needs approvers: nobody can approve requests of this type for the current user yet.',
    )
    approval_summary = fields.Char(compute='_compute_approval_summary', string='Who approves')
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

    ACTION_NAME_PATTERN = re.compile(r'(action|button)_[a-z0-9_]{1,80}')

    @api.model
    def _valid_action_name(self, name):
        """Only public action/button methods may run after approval."""
        return bool(name) and bool(self.ACTION_NAME_PATTERN.fullmatch(name))

    @api.constrains('action_name', 'model_id')
    def _check_action_name(self):
        for category in self:
            if not category.action_name:
                continue
            if not category.model_id:
                raise ValidationError(_('Choose a Target Model before setting an action to run after approval.'))
            if not self._valid_action_name(category.action_name):
                raise ValidationError(_('The action must be a public method starting with "action_" or "button_", for example action_confirm.'))
            if category.model_id.model in self.env and not callable(getattr(self.env[category.model_id.model], category.action_name, None)):
                raise ValidationError(_('The target model has no method named %s.', category.action_name))

    @api.constrains('approval_minimum', 'manager_approval', 'approver_ids')
    def _check_approval_minimum(self):
        for category in self:
            if category.approval_minimum < 1:
                raise ValidationError(_('At least one approval is needed.'))
            possible_approvers = len(category.approver_ids) + (1 if category.manager_approval else 0)
            if possible_approvers and category.approval_minimum > possible_approvers:
                raise ValidationError(_('"How many must approve" (%(needed)s) is more than the approvers set (%(total)s).',
                                        needed=category.approval_minimum, total=possible_approvers))

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

    @api.depends('approver_ids', 'manager_approval')
    @api.depends_context('uid')
    def _compute_setup_state(self):
        has_manager = bool(self.env.user.employee_id.parent_id.user_id)
        for category in self:
            ready = bool(category.approver_ids) or (category.manager_approval and has_manager)
            category.setup_state = 'ready' if ready else 'needs_approvers'

    @api.depends('approver_ids.user_id', 'approver_ids.required', 'manager_approval',
                 'approver_sequence', 'approval_minimum')
    def _compute_approval_summary(self):
        for category in self:
            names = ([_("Requester's manager")] if category.manager_approval else []) + \
                category.approver_ids.sorted('sequence').user_id.mapped('name')
            if not names:
                category.approval_summary = _('No approvers yet')
                continue
            joined = _(', then ').join(names) if category.approver_sequence else ', '.join(names)
            needed = category.approval_minimum
            category.approval_summary = _('%(who)s · %(count)s of %(total)s must approve',
                                          who=joined, count=min(needed, len(names)), total=len(names))

    def action_card_click(self):
        """Dashboard card: start a request when ready, otherwise lead to setup."""
        self.ensure_one()
        if self.setup_state == 'ready':
            return self.action_new_request()
        if self.env.user.has_group('approval_center.group_approval_center_manager'):
            return self.action_setup()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'warning', 'message': _('"%s" is not available yet: ask an Approvals manager to add approvers.', self.name)}}

    def action_setup(self):
        """Open the approval type form on its approvers (managers only)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current', 'name': self.name,
        }

    @api.depends('approver_ids.user_id')
    def _compute_selected_approver_user_ids(self):
        for category in self:
            category.selected_approver_user_ids = category.approver_ids.user_id

    def action_new_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New request'),
            'res_model': 'approval.center.request',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_policy_id': self.id},
        }

    def action_view_submitted_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Requests to review'),
            'res_model': 'approval.center.request',
            'view_mode': 'kanban,list,form',
            'domain': [('policy_id', '=', self.id), ('state', '=', 'submitted')],
            'context': {'default_policy_id': self.id},
        }
