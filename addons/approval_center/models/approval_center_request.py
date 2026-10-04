from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class ApprovalCenterRequest(models.Model):
    _name = 'approval.center.request'
    _description = 'Approval Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Approval Subject', required=True, tracking=True)
    state = fields.Selection([
        ('to_submit', 'To Submit'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], default='to_submit', required=True, tracking=True, index=True)
    policy_id = fields.Many2one(
        'approval.center.policy',
        string='Category',
        required=True,
        tracking=True,
        domain="[('active', '=', True)]",
    )
    approval_minimum = fields.Integer(related='policy_id.approval_minimum', readonly=True)
    approver_sequence = fields.Boolean(related='policy_id.approver_sequence', readonly=True)
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

    @api.onchange('policy_id')
    def _onchange_policy_id(self):
        for request in self:
            if request.policy_id and request.policy_id.model:
                request.target_model = request.policy_id.model
            request.approver_ids = [(5, 0, 0)] + request._get_policy_approver_commands()

    def action_submit(self):
        for request in self:
            if request.state != 'to_submit':
                raise UserError(_('Only requests to submit can be submitted.'))
            request._prepare_request_approvers()
            if not request.approver_ids:
                raise UserError(_('This category has no approvers. Ask an Approval Center manager to configure the category.'))
            request._check_required_fields()
            request._check_policy_matches_target()
            request.write({
                'state': 'submitted',
                'approver_ids': [(1, approver.id, {'status': 'submitted'}) for approver in request.approver_ids],
            })
            request._audit('submitted', _('Approval request submitted.'))
            request._schedule_review_activity()
            request._notify_approvers()

    def action_approve(self):
        for request in self:
            request._check_can_review()
            if request.state != 'submitted':
                raise UserError(_('Only submitted approval requests can be approved.'))
            approver = request._get_current_user_approver()
            if not approver and self.env.user.has_group('approval_center.group_approval_center_manager'):
                approver = self.env['approval.center.approver'].create({
                    'request_id': request.id,
                    'user_id': self.env.user.id,
                    'required': True,
                    'status': 'submitted',
                })
            approver.write({'status': 'approved'})
            approved_count = self.env['approval.center.approver'].search_count([
                ('request_id', '=', request.id),
                ('status', '=', 'approved'),
            ])
            values = {
                'approver_id': self.env.user.id,
                'failure_reason': False,
            }
            if approved_count >= request.approval_minimum:
                values.update({
                    'state': 'approved',
                    'approved_at': fields.Datetime.now(),
                })
            request.write(values)
            request.activity_feedback(['approval_center.mail_act_approval_review'])
            request._audit('approved', _('Approval request approved.'))

    def action_refuse(self):
        for request in self:
            request._check_can_review()
            if request.state != 'submitted':
                raise UserError(_('Only submitted requests can be refused.'))
            approver = request._get_current_user_approver()
            if not approver and self.env.user.has_group('approval_center.group_approval_center_manager'):
                approver = self.env['approval.center.approver'].create({
                    'request_id': request.id,
                    'user_id': self.env.user.id,
                    'required': True,
                    'status': 'submitted',
                })
            approver.write({'status': 'refused'})
            request.write({
                'state': 'refused',
                'approver_id': self.env.user.id,
                'refused_at': fields.Datetime.now(),
            })
            request.activity_feedback(['approval_center.mail_act_approval_review'])
            request._audit('refused', _('Approval request refused.'))

    def action_reject(self):
        return self.action_refuse()

    def action_cancel(self):
        for request in self:
            if request.state == 'to_submit':
                raise UserError(_('Requests to submit do not need to be cancelled.'))
            if request.requester_id != self.env.user and not self.env.user.has_group('approval_center.group_approval_center_manager'):
                raise AccessError(_('Only the requester or an Approval Center manager can cancel this request.'))
            request.write({'state': 'to_submit'})
            request.activity_feedback(['approval_center.mail_act_approval_review'])
            request._audit('cancelled', _('Approval request cancelled.'))

    def action_execute(self):
        for request in self:
            request._execute_approved_action()

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

    def _execute_approved_action(self):
        self.ensure_one()
        try:
            self._check_execution_policy()
            if not self.target_model or not self.target_res_id or not self.action_name:
                self.write({
                    'state': 'approved',
                    'executed_at': fields.Datetime.now(),
                    'failure_reason': False,
                })
                self._audit('executed', _('Approval completed without a linked backend action.'))
                return True
            record = self.env[self.target_model].browse(self.target_res_id).exists()
            if not record:
                raise UserError(_('Target record no longer exists.'))
            action = getattr(record, self.action_name, None)
            if not action or self.action_name.startswith('_'):
                raise UserError(_('Configured action is not available on the target record.'))
            result = action()
        except Exception as error:
            message = str(error)
            self.write({'failure_reason': message})
            self._audit('failed', _('Approval execution failed.'), result=message)
            raise
        self.write({
            'state': 'approved',
            'executed_at': fields.Datetime.now(),
            'failure_reason': False,
        })
        self._audit('executed', _('Approved action executed.'), result=repr(result))
        return result

    def _check_execution_policy(self):
        self.ensure_one()
        if self.state != 'approved':
            self._audit('blocked', _('Execution blocked: request is not approved.'))
            raise UserError(_('Only approved requests can be executed.'))
        self._check_policy_matches_target()

    def _check_policy_matches_target(self):
        self.ensure_one()
        if not self.policy_id.active:
            raise UserError(_('Approval category is not active.'))
        if self.target_model and self.policy_id.model and self.policy_id.model != self.target_model:
            raise UserError(_('Approval category target model does not match the request target.'))

    def _check_can_review(self):
        self.ensure_one()
        if self.env.user.has_group('approval_center.group_approval_center_manager'):
            return True
        if self._get_current_user_approver():
            return True
        raise AccessError(_('You are not allowed to approve this request.'))

    def _get_current_user_approver(self):
        self.ensure_one()
        return self.approver_ids.filtered(lambda approver: approver.user_id == self.env.user)[:1]

    def _prepare_request_approvers(self):
        self.ensure_one()
        if self.approver_ids:
            return
        commands = self._get_policy_approver_commands()
        if len(commands) < self.approval_minimum:
            raise UserError(_('This request has fewer approvers than the category minimum approval.'))
        self.write({'approver_ids': commands})

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
