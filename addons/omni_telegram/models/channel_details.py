"""Compact channel overview and manager-confirmed configuration dialogs."""
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class TelegramChannelDetails(models.Model):
    _inherit = 'omni.channel'

    telegram_overview_account_id = fields.Many2one('omni.account', compute='_compute_telegram_overview')
    telegram_overview_bot = fields.Char(compute='_compute_telegram_overview')
    telegram_overview_connected = fields.Boolean(compute='_compute_telegram_overview')
    telegram_overview_list_status = fields.Char(compute='_compute_telegram_list_status')
    telegram_overview_status = fields.Char(compute='_compute_telegram_overview')
    telegram_overview_receiving = fields.Char(compute='_compute_telegram_overview')
    telegram_overview_test_users = fields.Text(compute='_compute_telegram_test_users', groups='omni_channel.group_omni_manager')

    @api.depends('setup_completed_steps', 'is_telegram', 'telegram_overview_status', 'readiness')
    def _compute_telegram_list_status(self):
        labels = dict(self._fields['readiness']._description_selection(self.env))
        for channel in self:
            channel.telegram_overview_list_status = channel.telegram_overview_status if (
                channel.is_telegram and channel.setup_completed_steps == 5
            ) else labels.get(channel.readiness, '')

    @api.depends('selected_sender_id.account_id', 'setup_account_id',
                 'sender_ids.account_id.telegram_verified_at', 'setup_account_id.telegram_verified_at',
                 'sender_ids.account_id.telegram_sandbox_recipients', 'setup_account_id.telegram_sandbox_recipients',
                 'sender_ids.account_id.telegram_sandbox_authorized', 'setup_account_id.telegram_sandbox_authorized',
                 'endpoint_ids.state', 'endpoint_ids.policy_id.state',
                 'sender_ids.account_id.active', 'setup_account_id.active',
                 'sender_ids.account_id.telegram_bot_name', 'setup_account_id.telegram_bot_name',
                 'sender_ids.account_id.telegram_bot_username', 'setup_account_id.telegram_bot_username', 'active')
    def _compute_telegram_overview(self):
        for channel in self:
            account = channel.selected_sender_id.account_id or channel.setup_account_id
            channel.telegram_overview_account_id = account
            channel.telegram_overview_bot = ('%s%s' % (account.telegram_bot_name or account.name or '',
                (' · @' + account.telegram_bot_username) if account.telegram_bot_username else '')) if account else _('No connection')
            channel.telegram_overview_connected = bool(account.active and account.telegram_verified_at)
            channel.telegram_overview_status = _('Connected') if channel.telegram_overview_connected else _('Needs connection')
            channel.telegram_overview_receiving = _('Receiving messages') if (
                channel.active and account.active and account.telegram_sandbox_authorized
                and channel.endpoint_ids.filtered(lambda e: e.account_id == account and e._allowed())
            ) else _('Receiving paused')

    @api.depends('telegram_overview_account_id.telegram_sandbox_recipients')
    def _compute_telegram_test_users(self):
        for channel in self:
            channel.telegram_overview_test_users = channel.telegram_overview_account_id.telegram_sandbox_recipients or _('No test users')

    def action_telegram_open_inbox(self):
        self.ensure_one()
        self.check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('omni_channel.action_inbox')
        action.update(domain=[('channel_id', '=', self.id)], context=dict(self.env.context))
        return action

    def action_telegram_technical_configuration(self):
        self.ensure_one()
        self._telegram_details_guard()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only system administrators can configure channel infrastructure.'))
        return {'type': 'ir.actions.act_window', 'name': _('Technical configuration'),
            'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
            'views': [(self.env.ref('omni_channel.channel_form').id, 'form')],
            'context': dict(self.env.context, omni_technical=True)}

    def _telegram_details_guard(self):
        self.ensure_one()
        self._require_manager()
        self.check_access('write')
        account = self.telegram_overview_account_id
        account.check_access('write')
        if not self.is_telegram or not account or account.company_id != self.company_id or account.purpose_id != self.purpose_id or account.channel_type_id != self.channel_type_id:
            raise UserError(_('Select this channel’s Telegram connection.'))
        return account

    def _telegram_details_revision(self):
        self.ensure_one()
        account = self._telegram_details_guard()
        policy = self.setup_policy_id
        # Only an opaque digest is exposed; credentials are never read.
        return hashlib.sha256(repr((self.id, self.generation, self.name, str(self.write_date), account.id,
            str(account.write_date), account.telegram_sandbox_recipients, account.telegram_sandbox_authorized,
            policy.id, str(policy.write_date), policy.message_days, policy.payload_days, policy.blocked_days)).encode()).hexdigest()

    def _open_telegram_details(self, mode):
        self._telegram_details_guard()
        wizard = self.env['omni.telegram.channel.details'].create({'channel_id': self.id, 'mode': mode})
        return {'type': 'ir.actions.act_window', 'name': _('Channel settings') if mode == 'settings' else _('Edit test users'),
            'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}

    def action_telegram_settings(self):
        self.ensure_one()
        return self._open_telegram_details('settings')

    def action_telegram_edit_test_users(self):
        self.ensure_one()
        return self._open_telegram_details('test_users')


class TelegramChannelDetailsDialog(models.TransientModel):
    _name = 'omni.telegram.channel.details'
    _description = 'Telegram channel settings and test users'

    channel_id = fields.Many2one('omni.channel', required=True, readonly=True)
    mode = fields.Selection([('settings', 'Channel settings'), ('test_users', 'Edit test users')], required=True, readonly=True)
    revision = fields.Char(readonly=True)
    name = fields.Char(string='Channel name', required=True)
    bot = fields.Char(string='Connected bot', readonly=True)
    webhook_url = fields.Char(string='Webhook URL', readonly=True)
    message_days = fields.Integer(string='Messages', required=True)
    payload_days = fields.Integer(string='Pending messages', required=True)
    blocked_days = fields.Integer(string='Blocked metadata', required=True)
    test_user_ids = fields.Text(string='Test user IDs')

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            channel = self.env['omni.channel'].browse(values.get('channel_id')).exists()
            account = channel._telegram_details_guard()
            policy = channel.setup_policy_id
            values = dict(values, revision=channel._telegram_details_revision(), name=channel.name,
                bot=channel.telegram_overview_bot, webhook_url=channel.setup_callback_url,
                message_days=policy.message_days or 90, payload_days=policy.payload_days or 7,
                blocked_days=policy.blocked_days or 30, test_user_ids=account.telegram_sandbox_recipients)
            prepared.append(values)
        return super().create(prepared)

    def write(self, vals):
        if {'channel_id', 'mode', 'revision', 'bot', 'webhook_url'} & vals.keys():
            raise AccessError(_('Reopen the channel settings to change the connection.'))
        return super().write(vals)

    def action_save(self):
        self.ensure_one()
        self.check_access('write')
        channel = self.channel_id
        account = channel._telegram_details_guard()
        # Same lock order as sandbox updates: company, then channel.
        from odoo.addons.omni_channel.models.inbox import lock_company
        lock_company(account)
        channel._lock()
        channel.invalidate_recordset()
        account.invalidate_recordset()
        channel.setup_policy_id.invalidate_recordset()
        if self.revision != channel._telegram_details_revision():
            raise UserError(_('The channel changed. Close and reopen this form.'))
        with self.env.cr.savepoint():
            if self.mode == 'test_users':
                value = (self.test_user_ids or '').strip()
                if value != (account.telegram_sandbox_recipients or '').strip():
                    if account.telegram_sandbox_authorized:
                        account.action_revoke_telegram_sandbox()
                    account.write({'telegram_sandbox_recipients': value})
                    if value:
                        account.action_authorize_telegram_sandbox()
            else:
                policy = channel.setup_policy_id
                values = {key: self[key] for key in ('message_days', 'payload_days', 'blocked_days')}
                if not policy or any(policy[key] != value for key, value in values.items()):
                    # Validate before pausing; immutable policy history stays intact.
                    replacement = self.env['omni.inbound.policy'].create(dict(values, name=channel.name + ' retention', channel_id=channel.id))
                    if policy.state == 'active':
                        policy.action_pause()
                        replacement.action_activate()
                        for endpoint in channel.endpoint_ids.filtered(lambda e: e.state == 'enabled'):
                            endpoint.action_enable()
                if self.name != channel.name:
                    channel.write({'name': self.name})
                    channel._audit('channel.settings_saved', _('Channel name updated.'))
        return {'type': 'ir.actions.act_window_close'}
