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
    reason = fields.Text(string='Description')
    approved_at = fields.Datetime(readonly=True)
    executed_at = fields.Datetime(readonly=True)
    refused_at = fields.Datetime(readonly=True)
    failure_reason = fields.Text(readonly=True)
    audit_ids = fields.One2many('approval.center.audit', 'request_id', readonly=True)
    audit_count = fields.Integer(compute='_compute_audit_count')

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

    def action_submit(self):
        for request in self:
            if request.state != 'to_submit':
                raise UserError(_('Only requests to submit can be submitted.'))
            request._prepare_request_approvers()
            if not request.approver_ids:
                raise UserError(_('This category has no approvers. Ask an Approval Center manager to configure the category.'))
            request._check_policy_matches_target()
            request.write({
                'state': 'submitted',
                'approver_ids': [(1, approver.id, {'status': 'submitted'}) for approver in request.approver_ids],
            })
            request._audit('submitted', _('Approval request submitted.'))
            request._schedule_review_activity()

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
            request.activity_unlink(['approval_center.mail_act_approval_review'])
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
            request.activity_unlink(['approval_center.mail_act_approval_review'])
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
        commands = []
        manager = self.requester_id.employee_id.parent_id.user_id if self.policy_id.manager_approval else False
        if manager:
            commands.append((0, 0, {
                'sequence': 0,
                'user_id': manager.id,
                'required': True,
                'status': 'new',
            }))
        for approver in self.policy_id.approver_ids:
            if manager and approver.user_id == manager:
                continue
            commands.append((0, 0, {
                'sequence': approver.sequence,
                'user_id': approver.user_id.id,
                'required': approver.required,
                'status': 'new',
            }))
        if len(commands) < self.approval_minimum:
            raise UserError(_('This request has fewer approvers than the category minimum approval.'))
        self.write({'approver_ids': commands})

    def _schedule_review_activity(self):
        self.ensure_one()
        for approver in self.approver_ids.filtered(lambda line: line.user_id.active):
            self.activity_schedule(
                'approval_center.mail_act_approval_review',
                user_id=approver.user_id.id,
                note=_('Review approval request: %s') % self.name,
            )

    def _audit(self, event, message, result=False):
        self.ensure_one()
        self.env['approval.center.audit'].sudo().create({
            'request_id': self.id,
            'actor_id': self.env.user.id,
            'event': event,
            'message': message,
            'result': result or False,
        })
