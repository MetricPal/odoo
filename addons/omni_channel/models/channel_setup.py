"""Guided setup backed by the existing connection and activation mechanisms."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .command import internal, is_internal
from .foundation import protected_input


class ChannelSetup(models.Model):
    _inherit = 'omni.channel'

    setup_completed_steps = fields.Integer(string='Setup steps completed', default=0, readonly=True, copy=False)
    setup_completed_step_ids = fields.Json(readonly=True, copy=False)
    setup_receiving_deferred = fields.Boolean(readonly=True, copy=False)
    setup_receiving_ready = fields.Boolean(compute='_compute_setup_receiving_ready')
    setup_step_total = fields.Integer(compute='_compute_setup_progress')
    setup_progress_label = fields.Char(string='Setup', compute='_compute_setup_progress')

    @api.depends('setup_completed_steps')
    def _compute_setup_progress(self):
        for channel in self:
            channel.setup_step_total = 6
            channel.setup_progress_label = _('%s of 6 steps', channel.setup_completed_steps)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, {'setup_completed_steps', 'setup_completed_step_ids', 'setup_receiving_deferred'}, vals_list) and not is_internal(self):
            raise AccessError(_('Setup progress is recorded when you complete a step.'))
        return super().create(vals_list)

    def _completed_setup_steps(self):
        self.ensure_one()
        # Preserve progress recorded before per-step tracking was introduced.
        return list(self.setup_completed_step_ids) if self.setup_completed_step_ids is not False and self.setup_completed_step_ids is not None else list(range(self.setup_completed_steps))

    @api.depends('setup_endpoint_state', 'setup_endpoint_health', 'setup_callback_url')
    def _compute_setup_receiving_ready(self):
        for channel in self:
            channel.setup_receiving_ready = channel._is_setup_receiving_ready()

    def _is_setup_receiving_ready(self):
        self.ensure_one()
        return bool(self.setup_callback_url and self.setup_endpoint_state == 'enabled' and self.setup_endpoint_health == 'healthy')

    def action_setup_defer_receiving(self):
        self.ensure_one()
        self._require_manager()
        self._lock()
        completed = self._completed_setup_steps()
        if not {0, 1}.issubset(completed):
            raise UserError(_('Complete Credentials first.'))
        internal(self).write({'setup_receiving_deferred': True})
        return True

    def action_setup_complete_step(self, step):
        self.ensure_one()
        self._require_manager()
        self._lock()
        self.invalidate_recordset(['setup_completed_steps', 'setup_completed_step_ids', 'setup_receiving_deferred'])
        if type(step) is not int or not 0 <= step <= 5:
            raise UserError(_('Unknown setup step.'))
        completed = set(self._completed_setup_steps())
        prerequisites = set(range(step))
        if step in (3, 4) and self.setup_receiving_deferred:
            prerequisites.discard(2)
        if not prerequisites.issubset(completed):
            raise UserError(_('Complete the previous setup steps first.'))
        self.action_setup_validate_step(step)
        if step == 5 and not self._is_setup_receiving_ready():
            raise UserError(_('Receiving is not ready. Save this channel as a draft and finish receiving setup later.'))
        completed.add(step)
        values = {'setup_completed_steps': len(completed), 'setup_completed_step_ids': sorted(completed)}
        if step == 2:
            values['setup_receiving_deferred'] = False
        internal(self).write(values)
        return len(completed)

    def action_open_channel(self):
        self.ensure_one()
        self.check_access('read')
        if self.setup_completed_steps != 6:
            raise UserError(_('Use Start setup or Continue setup to finish this channel.'))
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': self.id, 'view_mode': 'form', 'target': 'current',
            'views': [(self.env.ref('omni_channel.channel_form').id, 'form')],
        }

    def action_continue_setup(self):
        self.ensure_one()
        self._require_manager()
        return {
            'type': 'ir.actions.act_window', 'name': _('Channel setup'),
            'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
            'views': [(self.env.ref('omni_channel.channel_setup_form').id, 'form')],
            'target': 'current',
            'context': dict(self.env.context, setup_completed_steps=self.setup_completed_steps, setup_completed_step_ids=self._completed_setup_steps()),
        }

    setup_account_id = fields.Many2one('omni.account', string='Connection', check_company=True, copy=False)
    setup_connection_mode = fields.Selection(
        [('new', 'Create new connection'), ('existing', 'Use existing connection')],
        string='Connection setup', compute='_compute_setup_connection_mode',
        store=True, readonly=False, copy=False,
    )

    @api.depends('setup_account_id')
    def _compute_setup_connection_mode(self):
        for channel in self:
            channel.setup_connection_mode = 'existing' if channel.setup_account_id else 'new'

    @api.onchange('setup_connection_mode')
    def _onchange_setup_connection_mode(self):
        if self.setup_connection_mode == 'new' and not self.setup_has_bindings:
            self.setup_account_id = False

    setup_description = fields.Text(string='Internal description')
    setup_sender_id = fields.Many2one('omni.outbound.sender', compute='_compute_setup_bindings')
    setup_endpoint_id = fields.Many2one('omni.inbound.endpoint', compute='_compute_setup_bindings')
    setup_policy_id = fields.Many2one('omni.inbound.policy', compute='_compute_setup_bindings')
    setup_callback_url = fields.Char(string='Callback URL', compute='_compute_setup_bindings')
    setup_callback_preview = fields.Char(compute='_compute_setup_bindings')
    setup_endpoint_state = fields.Selection(related='setup_endpoint_id.state', string='Receiving status')
    setup_endpoint_health = fields.Selection(related='setup_endpoint_id.health', string='Connection check')
    setup_policy_state = fields.Selection(related='setup_policy_id.state')
    setup_payload_days = fields.Integer(related='setup_policy_id.payload_days', readonly=False, string='Pending payload retention (days)')
    setup_message_days = fields.Integer(related='setup_policy_id.message_days', readonly=False, string='Message retention (days)')
    setup_blocked_days = fields.Integer(related='setup_policy_id.blocked_days', readonly=False, string='Blocked metadata retention (days)')
    setup_has_bindings = fields.Boolean(compute='_compute_setup_bindings')
    setup_conversation_id = fields.Many2one('omni.conversation', string='Test conversation', check_company=True, copy=False)
    setup_test_body = fields.Text(string='Test message', copy=False)

    @api.depends('sender_ids.account_id', 'endpoint_ids.account_id', 'setup_account_id', 'endpoint_ids.state')
    def _compute_setup_bindings(self):
        for channel in self:
            sender = channel.sender_ids.filtered(lambda s: s.account_id == channel.setup_account_id)[:1]
            endpoint = channel.endpoint_ids.filtered(lambda e: e.account_id == channel.setup_account_id)[:1]
            channel.setup_sender_id = sender
            channel.setup_endpoint_id = endpoint
            channel.setup_has_bindings = bool(channel.sender_ids or channel.endpoint_ids)
            channel.setup_callback_url = endpoint._get_webhook_url() if endpoint else False
            channel.setup_callback_preview = channel.setup_callback_url or (
                'https://channels.<your-domain>/omni/inbound/%s'
                % (endpoint.route_key if endpoint and endpoint.route_key else '<route_key>')
            )
            channel.setup_policy_id = self.env['omni.inbound.policy'].search(
                [('channel_id', '=', channel.id), ('state', '=', 'active')], limit=1,
            ) or self.env['omni.inbound.policy'].search(
                [('channel_id', '=', channel.id)], order='id desc', limit=1,
            ) if channel.id and isinstance(channel.id, int) else False

    @api.constrains('setup_account_id', 'company_id', 'purpose_id', 'channel_type_id')
    def _check_setup_account(self):
        for channel in self:
            account = channel.setup_account_id
            if account:
                account.check_access('read')
                if (account.company_id != channel.company_id or account.purpose_id != channel.purpose_id
                        or account.channel_type_id != channel.channel_type_id or not account.active):
                    raise ValidationError(_('Choose an active connection for this company, team and channel type.'))

    def write(self, values):
        if {'setup_completed_steps', 'setup_completed_step_ids', 'setup_receiving_deferred'} & values.keys() and not is_internal(self):
            raise AccessError(_('Setup progress is recorded when you complete a step.'))
        if 'setup_account_id' in values:
            for channel in self:
                channel._require_manager()
                channel._lock()
                if channel.setup_account_id.id != values['setup_account_id'] and (channel.sender_ids or channel.endpoint_ids):
                    raise UserError(_('This channel is already linked to a provider identity. Create another channel for another connection.'))
        reset_to = {}
        for channel in self:
            if any(key in values and channel[key].id != values[key] for key in ('company_id', 'purpose_id', 'channel_type_id')):
                reset_to[channel.id] = 0
            elif 'setup_account_id' in values and channel.setup_account_id.id != values['setup_account_id']:
                reset_to[channel.id] = min(channel.setup_completed_steps, 1)
        result = super().write(values)
        for channel in self:
            if channel.id in reset_to:
                internal(channel).write({'setup_completed_steps': reset_to[channel.id], 'setup_completed_step_ids': list(range(reset_to[channel.id])), 'setup_receiving_deferred': False})
        return result

    def action_setup_prepare_connection(self):
        """Adapter overrides may create draft bindings; never activate here."""
        self.ensure_one()
        self._require_manager()
        raise UserError(_('Guided connection setup is not available for this provider yet. Save this channel as a draft.'))

    def action_setup_validate_step(self, step):
        self.ensure_one()
        self._require_manager()
        if type(step) is not int or not 0 <= step <= 5:
            raise ValidationError(_('Unknown setup step.'))
        if step == 1:
            if not self.setup_account_id:
                raise UserError(_('Verify a new connection or select an existing connection before continuing.'))
            self.action_setup_prepare_connection()
        if step == 2:
            if not self.setup_endpoint_id:
                raise UserError(_('Complete Credentials first to prepare the receiving endpoint.'))
            if not self._is_setup_receiving_ready():
                raise UserError(_('Receiving is not ready. Choose Set up receiving later to continue configuring this draft.'))
        return True

    def action_setup_enable_receiving(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_callback_url:
            raise UserError(_('Ask your administrator to configure the public HTTPS channel address first.'))
        if not self.setup_policy_id or not self.setup_endpoint_id:
            raise UserError(_('Prepare the connection before enabling receiving.'))
        if self.setup_policy_id.state != 'active':
            self.setup_policy_id.action_activate()
        self.setup_endpoint_id.action_enable()
        return True

    def action_setup_verify_webhook(self):
        self.ensure_one()
        self._require_manager()
        raise UserError(_('Webhook verification is not supported by this provider yet.'))

    def action_setup_check_connection(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_endpoint_id:
            raise UserError(_('Complete Credentials first.'))
        self.setup_endpoint_id.action_check_health()
        return True

    def action_setup_prepare_test(self):
        self.ensure_one()
        self._require_manager()
        conversation = self.setup_conversation_id
        conversation.check_access('read')
        if not conversation or conversation.channel_id != self or not (self.setup_test_body or '').strip():
            raise UserError(_('Choose a verified conversation on this channel and enter a test message.'))
        action = conversation.action_prepare_reply()
        self.env['omni.command'].browse(action['res_id']).write({'body': self.setup_test_body})
        action['target'] = 'new'
        return action
