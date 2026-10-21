"""Frozen message preparation and a narrowly scoped Approval Center bridge."""

import hashlib
import json
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .foundation import protected_input

from odoo.addons.approval_center.models.common import capability

# Identity comparison makes the internal capability impossible to forge using
# JSON-RPC context, unlike a boolean 'approved' / 'skip_security' flag.
internal, is_internal = capability('_omni_internal')


def digest(payload):
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
        ).encode(),
    ).hexdigest()


class OmniChannelApproval(models.Model):
    _inherit = 'omni.channel'

    approval_type_id = fields.Many2one(
        'approval.center.policy', string='Message approval type', check_company=True,
    )

    def _advance_generation(self):
        super()._advance_generation()
        commands = (
            self.env['omni.command']
            .sudo()
            .search(
                [
                    ('channel_id', '=', self.id),
                    ('state', 'in', ['pending', 'approved', 'queued']),
                ],
            )
        )
        internal(commands).write(
            {
                'state': 'held',
                'held_reason': _('Runtime sender changed; submit a fresh revision.'),
            },
        )
        for command in commands:
            command._audit('message.held', _('Sender generation changed.'))

    def write(self, vals):
        result = super().write(vals)
        if 'approval_type_id' in vals:
            for channel in self:
                channel._audit(
                    'channel.approval_policy', _('Message approval policy changed.'),
                )
        return result


class OmniCommand(models.Model):
    _name = 'omni.command'
    _inherit = ['omni.scope.mixin']
    _description = 'Prepared Message'
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, default=lambda self: _('New message'))
    uuid = fields.Char(
        default=lambda self: str(uuid.uuid4()),
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    channel_id = fields.Many2one(
        'omni.channel', required=True, check_company=True, ondelete='restrict',
    )
    company_id = fields.Many2one(
        related='channel_id.company_id', store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related='channel_id.purpose_id', store=True, precompute=True,
    )
    requester_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, required=True, readonly=True,
    )
    recipient = fields.Char(
        required=True, help='Provider recipient identity, not a display name.',
    )
    body = fields.Text(required=True)
    reason = fields.Text(required=True)
    sender_id = fields.Many2one(
        'omni.outbound.sender', readonly=True, ondelete='restrict', check_company=True,
    )
    channel_generation = fields.Integer(readonly=True)
    payload_hash = fields.Char(readonly=True)
    payload = fields.Json(readonly=True)
    policy_hash = fields.Char(readonly=True)
    approval_request_id = fields.Many2one(
        'approval.center.request', readonly=True, copy=False, ondelete='restrict',
    )
    expires_at = fields.Datetime(readonly=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('pending', 'Pending approval'),
            ('approved', 'Approved'),
            ('queued', 'Queued'),
            ('held', 'Held'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    held_reason = fields.Char(readonly=True)
    _uuid_unique = models.Constraint(
        'UNIQUE(uuid)', 'Command identifiers must be unique.',
    )

    _protected = {
        'uuid',
        'requester_id',
        'sender_id',
        'channel_generation',
        'payload_hash',
        'payload',
        'policy_hash',
        'approval_request_id',
        'expires_at',
        'state',
        'held_reason',
        'company_id',
        'purpose_id',
    }

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._protected, vals_list) and not is_internal(self):
            raise AccessError(
                _('Approval evidence and command identity are managed by the server.'),
            )
        records = super().create(vals_list)
        for record in records:
            record.channel_id.check_access('read')
        return records

    def write(self, vals):
        if not is_internal(self):
            if self._protected & vals.keys():
                raise AccessError(_('Use the review actions to change command status.'))
            for record in self:
                if record.state != 'draft' or record.requester_id != self.env.user:
                    raise AccessError(
                        _('Only the owner can edit an unsubmitted draft.'),
                    )
        return super().write(vals)

    def unlink(self):
        if any(
            record.state != 'draft' or record.requester_id != self.env.user
            for record in self
        ):
            raise AccessError(_('Submitted messages are retained for audit.'))
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        self.check_access('read')
        return self.create(
            dict(
                {
                    'name': self.name,
                    'channel_id': self.channel_id.id,
                    'recipient': self.recipient,
                    'body': self.body,
                    'reason': self.reason,
                },
                **(default or {}),
            ),
        )

    def _lock(self):
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(
            'SELECT id FROM omni_command WHERE id = %s FOR UPDATE', [self.id],
        )
        self.invalidate_recordset()

    def _policy_document(self):
        policy = self.channel_id.approval_type_id
        if not policy or not policy.active or policy.company_id != self.company_id:
            raise UserError(
                _('Configure an active approval type for this company on the channel.'),
            )
        if policy.manager_approval:
            raise UserError(
                _('Use explicitly assigned approvers for communication requests.'),
            )
        if policy.model and (
            policy.model != 'omni.command'
            or policy.action_name != 'action_enqueue_approved'
        ):
            raise UserError(
                _(
                    'Use a general approval type or the approved Omni-Channel enqueue action.',
                ),
            )
        lines = policy.sudo().approver_ids.sorted(lambda line: (line.sequence, line.id))
        if not lines or policy.approval_minimum > len(lines):
            raise UserError(
                _('The approval type needs enough explicitly assigned approvers.'),
            )
        for line in lines:
            user = line.user_id
            if (
                not user.active
                or user.share
                or user == self.requester_id
                or user not in self.purpose_id.user_ids
                or self.company_id not in user.company_ids
                or not user.has_group('approval_center.group_approval_center_approver')
            ):
                raise UserError(
                    _(
                        'Each approver must be a different active internal user with approval, team and company access.',
                    ),
                )
        return {
            'id': policy.id,
            'minimum': policy.approval_minimum,
            'sequence': policy.approver_sequence,
            'version': fields.Datetime.to_string(policy.write_date),
            'approvers': [
                (line.user_id.id, line.sequence, line.required) for line in lines
            ],
        }

    def _extra_payload(self):
        return {}

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        self._lock()
        if self.state != 'draft' or self.requester_id != self.env.user:
            raise AccessError(_('Only the draft owner can submit this message.'))
        self.channel_id._lock()
        sender = self.channel_id.sender_ids.filtered('is_selected')
        if (
            len(sender) != 1
            or sender.health != 'healthy'
            or not sender.active
            or not self.channel_id.active
        ):
            raise UserError(
                _('Select and verify a runtime sender before submitting a message.'),
            )
        if (
            not self.body.strip()
            or not self.recipient.strip()
            or not self.reason.strip()
        ):
            raise UserError(_('Recipient, message and reason cannot be empty.'))
        policy_doc = self._policy_document()
        payload = {
            'schema': 1,
            'uuid': self.uuid,
            'company': self.company_id.id,
            'purpose': self.purpose_id.code,
            'channel': self.channel_id.id,
            'generation': self.channel_id.generation,
            'sender': sender.external_key,
            'account': sender.account_id.external_account_key,
            'recipient': self.recipient,
            'body': self.body,
            'operation': 'message.send',
            **self._extra_payload(),
        }
        request = internal(self.env['approval.center.request']).create(
            {
                'name': self.name,
                'policy_id': self.channel_id.approval_type_id.id,
                'company_id': self.company_id.id,
                'requester_id': self.requester_id.id,
                'omni_command_id': self.id,
                'target_model': 'omni.command',
                'target_res_id': self.id,
                'reason': self.reason,
                'state': 'submitted',
                'approver_ids': [
                    fields.Command.create(
                        {
                            'user_id': uid,
                            'sequence': sequence,
                            'required': required,
                            'status': 'submitted',
                        },
                    )
                    for uid, sequence, required in policy_doc['approvers']
                ],
            },
        )
        request._check_required_fields()
        internal(self).write(
            {
                'state': 'pending',
                'sender_id': sender.id,
                'channel_generation': self.channel_id.generation,
                'payload': payload,
                'payload_hash': digest(payload),
                'policy_hash': digest(policy_doc),
                'expires_at': fields.Datetime.now() + timedelta(hours=24),
                'approval_request_id': request.id,
            },
        )
        self._audit('message.submitted', _('Message frozen and submitted for review.'))
        return self.action_view_approval()

    def _check_frozen(self):
        if (
            not self.expires_at
            or self.expires_at <= fields.Datetime.now()
            or digest(self.payload) != self.payload_hash
            or self.channel_id.generation != self.channel_generation
            or not self.sender_id.is_selected
            or not self.channel_id.active
            or not self.sender_id.active
            or not self.sender_id.account_id.active
            or self.sender_id.health != 'healthy'
            or digest(self._policy_document()) != self.policy_hash
        ):
            raise UserError(
                _(
                    'This approval is stale or its configuration changed. Cancel and duplicate the draft for a fresh review.',
                ),
            )
        # Current requester authorization, not only worker/approver privileges.
        self.channel_id.with_user(self.requester_id).with_context(
            allowed_company_ids=[self.company_id.id],
        ).check_access('read')
        if not self.requester_id.active:
            raise AccessError(_('The requester is no longer active.'))

    def action_enqueue_approved(self):
        self.ensure_one()
        self.check_access('read')
        self._lock()
        if self.state == 'queued':
            return True
        if self.state != 'approved':
            raise AccessError(_('A valid approved request is required.'))
        self._check_frozen()
        request = self.approval_request_id
        if (
            self.state != 'approved'
            or request.state != 'approved'
            or request.omni_command_id != self
        ):
            raise AccessError(_('A valid approved request is required.'))
        doc = self._policy_document()
        approved = request.sudo().approver_ids.filtered(
            lambda line: line.status == 'approved',
        )
        required = {uid for uid, sequence, needed in doc['approvers'] if needed}
        if len(approved) < doc['minimum'] or not required.issubset(
            set(approved.user_id.ids),
        ):
            raise AccessError(_('The required approval evidence is missing.'))
        # Enqueue only: provider I/O belongs exclusively to the isolated worker.
        internal(self).write({'state': 'queued'})
        internal(request.sudo()).write({'executed_at': fields.Datetime.now()})
        self._audit(
            'message.queued',
            _(
                'Approved message queued. Dispatch requires an enabled channel and current recipient authorization.',
            ),
        )
        return True

    def action_cancel(self):
        self.ensure_one()
        self.check_access('read')
        self._lock()
        if self.requester_id != self.env.user:
            raise AccessError(_('Only the requester can cancel this prepared message.'))
        internal(self).write({'state': 'cancelled'})
        self._audit('message.cancelled', _('Prepared message cancelled.'))
        return True

    def action_view_approval(self):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'approval.center.request',
            'res_id': self.approval_request_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class OmniApprovalRequest(models.Model):
    _inherit = 'approval.center.request'

    omni_command_id = fields.Many2one(
        'omni.command', readonly=True, ondelete='restrict', copy=False,
    )
    omni_purpose_id = fields.Many2one(related='omni_command_id.purpose_id', store=True)
    omni_body = fields.Text(related='omni_command_id.body', string='Message content')
    omni_recipient = fields.Char(
        related='omni_command_id.recipient', string='Recipient',
    )
    omni_sender_id = fields.Many2one(
        related='omni_command_id.sender_id', string='Sending identity',
    )

    omni_sender_key = fields.Char(related='omni_command_id.sender_id.external_key', string='External sender identity')
    omni_expires_at = fields.Datetime(related='omni_command_id.expires_at', string='Approval expires')

    def _approval_trusted(self):
        return is_internal(self) or super()._approval_trusted()

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, {'omni_command_id', 'omni_purpose_id'}, vals_list) and not is_internal(self):
            raise AccessError(
                _('Communication approvals are created from a prepared message.'),
            )
        return super().create(vals_list)

    def write(self, vals):
        if not is_internal(self) and (
            {'omni_command_id', 'omni_purpose_id'} & vals.keys() or any(self.mapped('omni_command_id'))
        ):
            raise AccessError(
                _('Communication approvals are immutable. Use their review actions.'),
            )
        return super().write(vals)

    def unlink(self):
        if any(self.mapped('omni_command_id')):
            raise AccessError(_('Communication approval evidence must be retained.'))
        return super().unlink()

    def action_approve(self):
        for request in self:
            if not request.omni_command_id:
                super(OmniApprovalRequest, request).action_approve()
                continue
            request.check_access('read')
            command = request.omni_command_id
            command.check_access('read')
            command._lock()
            request.invalidate_recordset()
            command._check_frozen()
            if (
                request.state != 'submitted'
                or command.state != 'pending'
                or command.requester_id == self.env.user
            ):
                raise AccessError(
                    _('This request cannot be approved by you in its current state.'),
                )
            lines = request.sudo().approver_ids.sorted(
                lambda line: (line.sequence, line.id),
            )
            line = lines.filtered(lambda item: item.user_id == self.env.user)
            if len(line) != 1 or line.status != 'submitted':
                raise AccessError(
                    _('Only a pending assigned approver may review this request.'),
                )
            if not self.env.user.has_group(
                'approval_center.group_approval_center_approver',
            ):
                raise AccessError(_('Approval permission is required.'))
            if command._policy_document()['sequence'] and any(
                item.status != 'approved' for item in lines[: list(lines).index(line)]
            ):
                raise UserError(_('Earlier approvers must review this request first.'))
            internal(line).write({'status': 'approved'})
            approved = lines.filtered(lambda item: item.status == 'approved')
            required = lines.filtered('required')
            if len(approved) >= command._policy_document()['minimum'] and all(
                item.status == 'approved' for item in required
            ):
                internal(request.sudo()).write(
                    {
                        'state': 'approved',
                        'approved_at': fields.Datetime.now(),
                        'approver_id': self.env.uid,
                    },
                )
                internal(command.sudo()).write({'state': 'approved'})
            command._audit(
                'message.approved', _('Assigned approver recorded a decision.'),
            )
        return True

    def action_refuse(self):
        for request in self:
            if not request.omni_command_id:
                super(OmniApprovalRequest, request).action_refuse()
                continue
            request.check_access('read')
            command = request.omni_command_id
            command.check_access('read')
            command._lock()
            if (
                command.state != 'pending'
                or self.env.user not in request.sudo().approver_ids.user_id
            ):
                raise AccessError(
                    _('Only an assigned approver may refuse a pending request.'),
                )
            if not self.env.user.has_group(
                'approval_center.group_approval_center_approver',
            ):
                raise AccessError(_('Approval permission is required.'))
            internal(request.sudo()).write({'state': 'refused'})
            internal(command.sudo()).write(
                {'state': 'held', 'held_reason': _('Approval refused.')},
            )
            command._audit(
                'message.refused', _('Assigned approver refused the message.'),
            )
        return True

    def _execute_approved_action(self):
        self.ensure_one()
        if self.omni_command_id:
            return self.omni_command_id.action_enqueue_approved()
        return super()._execute_approved_action()


class OmniApproverLine(models.Model):
    _inherit = 'approval.center.approver'

    @api.model_create_multi
    def create(self, vals_list):
        if not is_internal(self):
            for original_vals in vals_list:
                vals = dict(original_vals)
                vals.setdefault('request_id', self.env.context.get('default_request_id'))
                if (
                    vals.get('request_id')
                    and self.env['approval.center.request']
                    .sudo()
                    .browse(vals['request_id'])
                    .omni_command_id
                ):
                    raise AccessError(
                        _('Communication approvers are frozen at submission.'),
                    )
        return super().create(vals_list)

    def write(self, vals):
        if not is_internal(self):
            incoming = (
                self.env['approval.center.request']
                .sudo()
                .browse(vals.get('request_id'))
            )
            if self.sudo().request_id.omni_command_id or incoming.omni_command_id:
                raise AccessError(
                    _('Communication approval evidence cannot be edited directly.'),
                )
        return super().write(vals)

    def unlink(self):
        if self.sudo().request_id.omni_command_id:
            raise AccessError(_('Communication approval evidence cannot be deleted.'))
        return super().unlink()
