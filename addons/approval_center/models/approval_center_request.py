from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.web.models.models import UnlinkBlockedError

from .common import approval_internal, approval_token_present

# Fields that only the review/execution actions may change.
DECISION_FIELDS = {
    'state', 'requester_id', 'approver_id', 'approved_at', 'executed_at',
    'refused_at', 'failure_reason', 'review_minimum', 'review_sequence',
}
# Business content frozen once a request leaves "To Submit".
CONTENT_FIELDS = {
    'name', 'policy_id', 'company_id', 'date_start', 'date_end', 'date',
    'partner_id', 'document_ids', 'item', 'quantity', 'amount', 'reference',
    'payment', 'location', 'reason', 'approver_ids',
}
# Technical execution target: set by integrations or Approval Center administrators.
TARGET_FIELDS = {'target_model', 'target_res_id'}


class ApprovalCenterRequest(models.Model):
    _name = 'approval.center.request'
    _description = 'Approval Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Approval Subject', required=True, tracking=True)
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('to_submit', 'To Submit'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], default='to_submit', required=True, tracking=True, index=True, readonly=True)
    policy_id = fields.Many2one(
        'approval.center.policy',
        string='Approval type',
        required=True,
        tracking=True,
        domain="[('active', '=', True)]",
    )
    approval_minimum = fields.Integer(related='policy_id.approval_minimum', readonly=True)
    approver_sequence = fields.Boolean(related='policy_id.approver_sequence', readonly=True)
    review_minimum = fields.Integer(
        readonly=True, copy=False,
        help='Minimum approvals frozen when the request was submitted.',
    )
    review_sequence = fields.Boolean(
        readonly=True, copy=False,
        help='Whether approvers must decide in order, frozen when the request was submitted.',
    )
    action_name = fields.Char(related='policy_id.action_name', store=True, readonly=True)
    has_document = fields.Selection(related='policy_id.has_document', readonly=True)
    has_partner = fields.Selection(related='policy_id.has_partner', readonly=True)
    has_date = fields.Selection(related='policy_id.has_date', readonly=True)
    has_period = fields.Selection(related='policy_id.has_period', readonly=True)
    has_items = fields.Selection(related='policy_id.has_items', readonly=True)
    has_quantity = fields.Selection(related='policy_id.has_quantity', readonly=True)
    has_amount = fields.Selection(related='policy_id.has_amount', readonly=True)
    has_reference = fields.Selection(related='policy_id.has_reference', readonly=True)
    has_payment = fields.Selection(related='policy_id.has_payment', readonly=True)
    has_location = fields.Selection(related='policy_id.has_location', readonly=True)
    target_model = fields.Char(tracking=True)
    target_res_id = fields.Integer(string='Target Record ID', tracking=True)
    requester_id = fields.Many2one(
        'res.users',
        string='Request Owner',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
        tracking=True,
    )
    approver_id = fields.Many2one('res.users', string='Last Approver', readonly=True, tracking=True)
    approver_ids = fields.One2many(
        'approval.center.approver',
        'request_id',
        string='Approver(s)',
        copy=False,
    )
    selected_approver_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_selected_approver_user_ids',
    )
    approved_count = fields.Integer(compute='_compute_approval_counts')
    refused_count = fields.Integer(compute='_compute_approval_counts')
    waiting_for = fields.Char(
        compute='_compute_waiting_for',
        help='Approvers whose decision is still needed.',
    )
    can_review = fields.Boolean(compute='_compute_can_review')
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )
    date_start = fields.Datetime(string='From')
    date_end = fields.Datetime(string='To')
    date = fields.Date()
    partner_id = fields.Many2one('res.partner', string='Contact')
    document_ids = fields.Many2many('ir.attachment', string='Documents')
    item = fields.Char(string='Items')
    quantity = fields.Float()
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(currency_field='currency_id')
    reference = fields.Char()
    payment = fields.Char()
    location = fields.Char()
    reason = fields.Text(string='Description')
    approved_at = fields.Datetime(readonly=True)
    executed_at = fields.Datetime(readonly=True)
    refused_at = fields.Datetime(readonly=True)
    failure_reason = fields.Text(readonly=True)
    audit_ids = fields.One2many('approval.center.audit', 'request_id', readonly=True)
    audit_count = fields.Integer(compute='_compute_audit_count')

    # ------------------------------------------------------------------
    # Trust boundary
    # ------------------------------------------------------------------

    def _approval_trusted(self):
        """Whether the current call may perform governed state changes.

        Integrations (Workflows, Omnichannel, Social) extend this with their own
        server-side capability. ``sudo`` is server code only and stays trusted.
        """
        return self.env.su or approval_token_present(self)

    def _is_approval_manager(self):
        return self.env.user.has_group('approval_center.group_approval_center_manager')

    @api.model_create_multi
    def create(self, vals_list):
        if not self._approval_trusted():
            for vals in vals_list:
                decided = {name for name in DECISION_FIELDS - {'requester_id', 'state'} if vals.get(name)}
                if decided or vals.get('state', 'to_submit') != 'to_submit':
                    raise AccessError(_('Submit the request and use its review actions to change its status.'))
                if vals.get('requester_id', self.env.uid) != self.env.uid:
                    raise AccessError(_('You can only create approval requests for yourself.'))
                if TARGET_FIELDS & vals.keys() and not self._is_approval_manager():
                    policy = self.env['approval.center.policy'].browse(vals.get('policy_id')).exists()
                    # The category model is the only target a requester may imply.
                    if vals.get('target_res_id') or (vals.get('target_model') and vals['target_model'] != policy.model):
                        raise AccessError(_('Only an Approval Center administrator can link a request to a record.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self._approval_trusted():
            if DECISION_FIELDS & vals.keys():
                raise AccessError(_('Use Submit, Approve, Refuse or Cancel. Request status cannot be edited directly.'))
            if (CONTENT_FIELDS | TARGET_FIELDS) & vals.keys():
                for request in self:
                    if request.state != 'to_submit':
                        raise UserError(_('Submitted requests are frozen. Cancel the request to change it.'))
            if TARGET_FIELDS & vals.keys() and not self._is_approval_manager():
                raise AccessError(_('Only an Approval Center administrator can link a request to a record.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            # Drafts that never went to review can be deleted; the rest is audit trail.
            blocked = self.filtered(lambda request: request.state != 'to_submit' or request.sudo().audit_ids)
            if blocked:
                # Same error as a record still in use: the web client offers "Archive" right away.
                error = UnlinkBlockedError(_(
                    'Requests that went to review are kept for the audit trail. Archive them instead: '
                    'they disappear from the lists and can be found with the Archived filter.'
                ))
                error.context = {
                    'archivable': True,
                    'model_name': _('the approval history (audit trail)'),
                    'res_model': self._name,
                    'res_ids': self.ids,
                    'blocked_ids': blocked.ids,
                }
                raise error
        return super().unlink()

    # ------------------------------------------------------------------
    # Defaults and computes
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        policy_id = values.get('policy_id') or self.env.context.get('default_policy_id')
        policy = self.env['approval.center.policy'].browse(policy_id).exists()
        if policy:
            requester = self.env['res.users'].browse(values.get('requester_id')).exists() or self.env.user
            if policy.model:
                values['target_model'] = policy.model
            values['approver_ids'] = self._get_approval_type_approver_commands(policy, requester)
        return values

    @api.depends('audit_ids')
    def _compute_audit_count(self):
        for request in self:
            request.audit_count = len(request.audit_ids)

    @api.depends('approver_ids.status')
    def _compute_approval_counts(self):
        for request in self:
            request.approved_count = len(request.approver_ids.filtered(lambda approver: approver.status == 'approved'))
            request.refused_count = len(request.approver_ids.filtered(lambda approver: approver.status == 'refused'))

    @api.depends('approver_ids.user_id')
    def _compute_selected_approver_user_ids(self):
        for request in self:
            request.selected_approver_user_ids = request.approver_ids.user_id

    @api.depends('state', 'approver_ids.status', 'approver_ids.required', 'approver_ids.sequence', 'review_sequence')
    def _compute_waiting_for(self):
        for request in self:
            if request.state != 'submitted':
                request.waiting_for = False
                continue
            pending = request._ordered_lines().filtered(lambda line: line.status == 'submitted')
            if request.review_sequence:
                pending = pending[:1]
            request.waiting_for = ', '.join(pending.user_id.mapped('name')) or False

    @api.depends_context('uid')
    @api.depends('state', 'approver_ids.status', 'approver_ids.user_id', 'requester_id')
    def _compute_can_review(self):
        for request in self:
            try:
                request._check_can_review()
            except (AccessError, UserError):
                request.can_review = False
            else:
                request.can_review = request.state == 'submitted'

    @api.onchange('policy_id')
    def _onchange_policy_id(self):
        for request in self:
            if request.policy_id and request.policy_id.model:
                request.target_model = request.policy_id.model
            request.approver_ids = [(5, 0, 0)] + request._get_policy_approver_commands()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_submit(self):
        for request in self:
            if request.state != 'to_submit':
                raise UserError(_('Only requests to submit can be submitted.'))
            if request.requester_id != self.env.user and not request._is_approval_manager() and not request._approval_trusted():
                raise AccessError(_('Only the requester can submit this request.'))
            governed = approval_internal(request)
            governed._prepare_request_approvers()
            if not request.approver_ids:
                raise UserError(_(
                    'Nobody can approve "%s" requests for you yet: it has no approvers, and no manager is set '
                    'on your employee record. Ask an Approvals manager to add approvers.', request.policy_id.display_name))
            request._check_required_fields()
            request._check_policy_matches_target()
            minimum = request.policy_id.approval_minimum
            if len(request.approver_ids) < minimum:
                raise UserError(_(
                    '"%(type)s" needs %(needed)s approvals but only %(count)s approver(s) are available for you. '
                    'Ask an Approvals manager to add approvers.',
                    type=request.policy_id.display_name, needed=minimum, count=len(request.approver_ids)))
            governed.write({
                'state': 'submitted',
                'review_minimum': minimum,
                'review_sequence': request.policy_id.approver_sequence,
                'approved_at': False,
                'refused_at': False,
                'failure_reason': False,
                'approver_ids': [(1, approver.id, {'status': 'submitted'}) for approver in request.approver_ids],
            })
            request._audit('submitted', _('Approval request submitted.'))
            request._schedule_review_activity()
            request._notify_approvers()

    def action_approve(self):
        for request in self:
            request._check_can_review()
            approver = request._get_current_user_approver()
            override = not approver
            if override:
                # Administrator decision outside the designated approver list.
                approver = approval_internal(self.env['approval.center.approver']).create({
                    'request_id': request.id,
                    'user_id': self.env.user.id,
                    'sequence': max(request.approver_ids.mapped('sequence') or [0]) + 1,
                    'required': False,
                    'status': 'submitted',
                })
            approval_internal(approver).write({'status': 'approved'})
            values = {'approver_id': self.env.user.id, 'failure_reason': False}
            if request._approval_complete():
                values.update({'state': 'approved', 'approved_at': fields.Datetime.now()})
            approval_internal(request).write(values)
            request.activity_feedback(['approval_center.mail_act_approval_review'], user_id=self.env.uid)
            if request.state == 'approved':
                request.activity_unlink(['approval_center.mail_act_approval_review'])
            request._audit('approved', _('Administrator override: approval recorded.') if override else _('Approval recorded.'))

    def action_refuse(self):
        for request in self:
            request._check_can_review()
            approver = request._get_current_user_approver()
            override = not approver
            if override:
                approver = approval_internal(self.env['approval.center.approver']).create({
                    'request_id': request.id,
                    'user_id': self.env.user.id,
                    'sequence': max(request.approver_ids.mapped('sequence') or [0]) + 1,
                    'required': False,
                    'status': 'submitted',
                })
            approval_internal(approver).write({'status': 'refused'})
            approval_internal(request).write({
                'state': 'refused',
                'approver_id': self.env.user.id,
                'refused_at': fields.Datetime.now(),
            })
            request.activity_unlink(['approval_center.mail_act_approval_review'])
            request._audit('refused', _('Administrator override: request refused.') if override else _('Approval request refused.'))

    def action_reject(self):
        return self.action_refuse()

    def action_cancel(self):
        for request in self:
            if request.state == 'to_submit':
                raise UserError(_('Requests to submit do not need to be cancelled.'))
            if request.executed_at:
                raise UserError(_('This request was already executed and cannot be cancelled.'))
            if request.requester_id != self.env.user and not request._is_approval_manager():
                raise AccessError(_('Only the requester or an Approval Center manager can cancel this request.'))
            approval_internal(request).write({
                'state': 'to_submit',
                'approved_at': False,
                'refused_at': False,
                'approver_ids': [(1, line.id, {'status': 'new'}) for line in request.approver_ids],
            })
            request.activity_unlink(['approval_center.mail_act_approval_review'])
            request._audit('cancelled', _('Approval request cancelled.'))

    def action_execute(self):
        result = True
        for request in self:
            result = request._execute_approved_action()
        return result

    def action_view_audits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Approval Audit'),
            'res_model': 'approval.center.audit',
            'view_mode': 'list,form',
            'domain': [('request_id', '=', self.id)],
            'context': {'default_request_id': self.id},
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_approved_action(self):
        self.ensure_one()
        self._check_execution_policy()
        if self.requester_id != self.env.user and not self._is_approval_manager():
            raise AccessError(_('Only the requester or an Approval Center manager can execute this request.'))
        governed = approval_internal(self)
        if not self.target_model or not self.target_res_id or not self.action_name:
            governed.write({'executed_at': fields.Datetime.now(), 'failure_reason': False})
            self._audit('executed', _('Approval completed without a linked backend action.'))
            return True
        try:
            # The savepoint undoes partial business writes; the failure is then
            # recorded in the outer transaction so the audit is not rolled back.
            with self.env.cr.savepoint():
                record = self.env[self.target_model].browse(self.target_res_id).exists()
                if not record:
                    raise UserError(_('Target record no longer exists.'))
                action = getattr(record, self.action_name, None)
                if not callable(action) or not self.env['approval.center.policy']._valid_action_name(self.action_name):
                    raise UserError(_('Configured action is not available on the target record.'))
                result = action()
        except (UserError, AccessError, ValueError) as error:
            self.env.invalidate_all()
            message = str(error)
            governed.write({'failure_reason': message})
            self._audit('failed', _('Approval execution failed.'), result=message)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Execution failed'),
                    'message': message,
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        governed.write({'executed_at': fields.Datetime.now(), 'failure_reason': False})
        self._audit('executed', _('Approved action executed.'), result=repr(result)[:2000])
        return result

    def _check_execution_policy(self):
        self.ensure_one()
        if self.state != 'approved':
            self._audit('blocked', _('Execution blocked: request is not approved.'))
            raise UserError(_('Only approved requests can be executed.'))
        if self.executed_at:
            self._audit('blocked', _('Execution blocked: request was already executed.'))
            raise UserError(_('This request was already executed.'))
        self._check_policy_matches_target()

    def _check_policy_matches_target(self):
        self.ensure_one()
        if not self.policy_id.active:
            raise UserError(_('This approval type is archived.'))
        if self.policy_id.action_name and not self.policy_id.model:
            raise UserError(_('This approval type runs an action but has no target model. Ask an administrator to fix the approval type.'))
        if self.target_model and self.policy_id.model and self.policy_id.model != self.target_model:
            raise UserError(_('The approval type\'s target model does not match the request target.'))

    # ------------------------------------------------------------------
    # Review rules
    # ------------------------------------------------------------------

    def _ordered_lines(self):
        self.ensure_one()
        return self.approver_ids.sorted(lambda line: (line.sequence, line.id))

    def _check_can_review(self):
        """Raise unless the current user may decide now. Integrations override."""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError(_('Only submitted requests can be reviewed.'))
        user = self.env.user
        if self.requester_id == user and not self.policy_id.allow_self_approval:
            raise AccessError(_('You cannot approve or refuse your own request.'))
        line = self._get_current_user_approver()
        if not line:
            if self._is_approval_manager():
                return True
            raise AccessError(_('You are not allowed to approve this request.'))
        if line.status != 'submitted':
            raise UserError(_('You already recorded your decision on this request.'))
        if self.review_sequence and self._ordered_lines().filtered(
            lambda other: (other.sequence, other.id) < (line.sequence, line.id) and other.status != 'approved'
        ):
            raise UserError(_('An earlier approver must decide first.'))
        return True

    def _approval_complete(self):
        """Minimum count reached and every required approver approved."""
        self.ensure_one()
        lines = self.approver_ids
        minimum = self.review_minimum or self.policy_id.approval_minimum or 1
        approved = lines.filtered(lambda line: line.status == 'approved')
        missing_required = lines.filtered(lambda line: line.required and line.status != 'approved')
        return len(approved) >= minimum and not missing_required

    def _get_current_user_approver(self):
        self.ensure_one()
        return self.approver_ids.filtered(lambda approver: approver.user_id == self.env.user)[:1]

    def _prepare_request_approvers(self):
        self.ensure_one()
        if self.approver_ids:
            return
        commands = self._get_policy_approver_commands()
        if not commands:
            raise UserError(_(
                'Nobody can approve "%s" requests for you yet: it has no approvers, and no manager is set '
                'on your employee record. Ask an Approvals manager to add approvers.', self.policy_id.display_name))
        if len(commands) < self.approval_minimum:
            raise UserError(_(
                '"%(type)s" needs %(needed)s approvals but only %(count)s approver(s) are available for you. '
                'Ask an Approvals manager to add approvers.',
                type=self.policy_id.display_name, needed=self.approval_minimum, count=len(commands)))
        approval_internal(self).write({'approver_ids': commands})

    def _get_policy_approver_commands(self):
        self.ensure_one()
        if not self.policy_id:
            return []
        return self._get_approval_type_approver_commands(self.policy_id, self.requester_id)

    @api.model
    def _get_approval_type_approver_commands(self, policy, requester):
        commands = []
        manager = requester.employee_id.parent_id.user_id if policy.manager_approval else False
        if manager:
            commands.append((0, 0, {
                'sequence': 0,
                'user_id': manager.id,
                'required': True,
                'status': 'new',
            }))
        for approver in policy.approver_ids:
            if manager and approver.user_id == manager:
                continue
            commands.append((0, 0, {
                'sequence': approver.sequence,
                'user_id': approver.user_id.id,
                'required': approver.required,
                'status': 'new',
            }))
        return commands

    def _check_required_fields(self):
        self.ensure_one()
        required_fields = [
            ('has_document', 'document_ids', _('Document')),
            ('has_partner', 'partner_id', _('Contact')),
            ('has_date', 'date', _('Date')),
            ('has_items', 'item', _('Items')),
            ('has_quantity', 'quantity', _('Quantity')),
            ('has_amount', 'amount', _('Amount')),
            ('has_reference', 'reference', _('Reference')),
            ('has_payment', 'payment', _('Payment')),
            ('has_location', 'location', _('Location')),
        ]
        missing = [label for option_field, value_field, label in required_fields if self[option_field] == 'required' and not self[value_field]]
        if self.has_period == 'required' and (not self.date_start or not self.date_end):
            missing.append(_('Period'))
        if missing:
            raise UserError(_('Please complete the required fields: %s') % ', '.join(missing))

    def _schedule_review_activity(self):
        self.ensure_one()
        for approver in self.approver_ids.filtered(lambda line: line.user_id.active):
            self.activity_schedule(
                'approval_center.mail_act_approval_review',
                user_id=approver.user_id.id,
                summary=_('Review approval request: %s') % self.name,
                note=_('Review approval request: %s') % self.name,
            )

    def _notify_approvers(self):
        self.ensure_one()
        approvers = self.approver_ids.filtered(lambda line: line.user_id.active and line.user_id.partner_id)
        partner_ids = approvers.user_id.partner_id.ids
        if not partner_ids:
            return False
        self.with_context(mail_notify_force_send=True).message_notify(
            partner_ids=partner_ids,
            subject=_('Approval request submitted: %s') % self.name,
            body=_(
                '%(requester)s submitted approval request "%(request)s" in %(category)s.',
                requester=self.requester_id.display_name,
                request=self.name,
                category=self.policy_id.display_name,
            ),
            model=self._name,
            res_id=self.id,
            force_send=True,
        )
        return True

    def _audit(self, event, message, result=False):
        self.ensure_one()
        self.env['approval.center.audit'].sudo().create({
            'request_id': self.id,
            'actor_id': self.env.user.id,
            'event': event,
            'message': message,
            'result': result or False,
        })


    @api.model
    def action_pick_type(self):
        """New request: choose the approval type first."""
        action = self.env['ir.actions.act_window']._for_xml_id('approval_center.action_approval_center_dashboard')
        action['name'] = _('New request: choose a type')
        return action
