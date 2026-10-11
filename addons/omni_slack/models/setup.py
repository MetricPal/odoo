"""Slack-only setup through existing scoped Odoo records and public actions."""
import re
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import valid_callback_url
from ..providers import api as slack, vault

PROFILE = {'slack_workspace_id', 'slack_user_id', 'slack_app_id', 'slack_verified_at'}
CHECK = {'slack_verified_reference', 'slack_verified_url'}


class SlackAccount(models.Model):
    _inherit = 'omni.account'

    slack_workspace_id = fields.Char(readonly=True, copy=False)
    slack_user_id = fields.Char(readonly=True, copy=False)
    slack_app_id = fields.Char(readonly=True, copy=False)
    slack_verified_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, PROFILE, vals_list) and not is_internal(self):
            raise AccessError(_('Slack details are recorded by verification.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, PROFILE, [values]) and not is_internal(self):
            raise AccessError(_('Slack details are recorded by verification.'))
        return super().write(values)

    def _slack_credentials(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'slack' or not self.active or not self.slack_verified_at:
            raise UserError(_('Verify the Slack app first.'))
        try:
            return vault.load(self.credential_reference, database=self.env.cr.dbname,
                company_id=self.company_id.id, purpose_id=self.purpose_id.id,
                bot_id=self.external_account_key, workspace_id=self.slack_workspace_id)
        except Exception:
            raise UserError(_('Saved Slack credentials are unavailable.')) from None

    def _adapter_config(self):
        result = super()._adapter_config()
        if self.channel_type_id.code == 'slack':
            result.update(database=self.env.cr.dbname, company_id=self.company_id.id,
                          purpose_id=self.purpose_id.id, workspace_id=self.slack_workspace_id)
        return result


class SlackEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    slack_verified_reference = fields.Char(readonly=True, copy=False, groups='base.group_no_one')
    slack_verified_url = fields.Char(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, CHECK, vals_list):
            raise AccessError(_('Slack callback verification is server-managed.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, CHECK, [values]) and not is_internal(self):
            raise AccessError(_('Slack callback verification is server-managed.'))
        if 'webhook_url_override' in values:
            self._require_manager()
            for endpoint in self.filtered(lambda e: e.channel_type_id.code == 'slack'):
                value = values['webhook_url_override']
                if value and not valid_callback_url(value, endpoint.route_key):
                    raise UserError(_('Use a public HTTPS URL and keep the channel path.'))
                if value != endpoint.webhook_url_override:
                    endpoint.channel_id._slack_before_connection_change()
                    internal(endpoint.sudo()).write({'slack_verified_reference': False, 'slack_verified_url': False,
                                                    'state': 'disabled', 'health': 'unchecked'})
                    completed = [s for s in endpoint.channel_id._completed_setup_steps() if s < 2]
                    internal(endpoint.channel_id).write({'setup_completed_step_ids': completed,
                                                        'setup_completed_steps': len(completed)})
        return super().write(values)

    def _slack_verified(self):
        self.ensure_one()
        return bool(self.sudo().slack_verified_reference == self.account_id.credential_reference
                    and self.slack_verified_url and self.slack_verified_url == self._get_webhook_url())

    def _config(self):
        result = super()._config()
        if self.channel_type_id.code == 'slack':
            result['slack_verified'] = self._slack_verified()
        return result

    def _allowed(self, policy=None):
        return super()._allowed(policy) and (self.channel_type_id.code != 'slack' or self._slack_verified())

    def _slack_challenge(self, raw, headers, url):
        if not self.env.su:
            raise AccessError(_('Only verified transport may confirm a callback.'))
        self.ensure_one()
        self.channel_id._lock()
        self.invalidate_recordset()
        if not self.active or not self.account_id.active or not self.channel_id.active or self.channel_type_id.code != 'slack':
            raise ValueError('scope')
        def key(value):
            p = urlsplit(value or '')
            return p.scheme, p.hostname, p.port or 443, p.path
        if key(url) != key(self._get_webhook_url()):
            raise ValueError('url')
        from ..providers.adapter import bundle
        from ..providers.webhook import authenticated, challenge
        credentials = bundle(self._config())
        value = authenticated(raw, headers, credentials['signing_secret'])
        result = challenge(value)
        internal(self).write({'slack_verified_reference': self.account_id.credential_reference,
                             'slack_verified_url': self._get_webhook_url()})
        return result


class SlackChannel(models.Model):
    _inherit = 'omni.channel'

    is_slack = fields.Boolean(compute='_compute_is_slack')
    slack_credentials_ui = fields.Json(compute='_compute_slack_credentials_ui', groups='omni_channel.group_omni_manager')

    @api.depends('channel_type_id.code')
    def _compute_is_slack(self):
        for channel in self:
            channel.is_slack = channel.channel_type_id.code == 'slack'

    @api.depends('setup_account_id')
    def _compute_slack_credentials_ui(self):
        for channel in self:
            account = channel.setup_account_id
            channel.slack_credentials_ui = {'name': account.name, 'workspace': account.slack_workspace_id} if channel.is_slack and account.slack_verified_at else {}

    def _require_slack_setup(self):
        self.ensure_one()
        self._require_manager()
        self._check_scope()
        if not self.active or not self.is_slack:
            raise UserError(_('Choose an active Slack channel.'))

    def action_slack_connect(self, token, signing_secret, app_id):
        self._require_slack_setup()
        scope = (self.company_id.id, self.purpose_id.id, self.channel_type_id.id)
        if not isinstance(signing_secret, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', signing_secret) or not slack.valid_id(app_id, 'A'):
            raise UserError(_('Enter the signing secret and app ID from Slack Basic Information.'))
        try:
            profile = slack.verify(token)
        except Exception:
            raise UserError(_('Check the bot token and Slack app permissions.')) from None
        self._lock()
        self.invalidate_recordset()
        self._require_slack_setup()
        if scope != (self.company_id.id, self.purpose_id.id, self.channel_type_id.id) or self.setup_account_id or self.sender_ids or self.endpoint_ids:
            raise UserError(_('This channel changed or already has a connection.'))
        credentials = dict(database=self.env.cr.dbname, company_id=self.company_id.id, purpose_id=self.purpose_id.id,
            workspace_id=profile['team_id'], bot_id=profile['bot_id'], user_id=profile['user_id'],
            app_id=app_id, token=token, signing_secret=signing_secret)
        reference = vault.store(credentials)
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        try:
            with self.env.cr.savepoint():
                account = internal(self.env['omni.account']).create({'name': profile['name'],
                    'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
                    'channel_type_id': self.channel_type_id.id, 'external_account_key': profile['bot_id'],
                    'namespace': profile['team_id'], 'credential_reference': reference,
                    'slack_workspace_id': profile['team_id'], 'slack_user_id': profile['user_id'],
                    'slack_app_id': app_id, 'slack_verified_at': fields.Datetime.now()})
                self.write({'setup_account_id': account.id})
                self.action_setup_prepare_connection()
                self._audit('slack.credentials_verified', str(account.id))
        except Exception:
            vault.remove(reference, database)
            raise
        return True

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_slack:
            return super().action_setup_prepare_connection()
        self._require_slack_setup()
        self._check_setup_account()
        self._lock()
        self.invalidate_recordset()
        account = self.setup_account_id
        if not account:
            raise UserError(_('Connect the Slack app first.'))
        account._slack_credentials()
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            if self.env[model].sudo().with_context(active_test=False).search_count([('account_id','=',account.id), ('channel_id','!=',self.id)]):
                raise UserError(_('This Slack app is already assigned to another channel.'))
            bindings = self.sender_ids if model == 'omni.outbound.sender' else self.endpoint_ids
            if not bindings:
                self.env[model].create({'name': self.name, 'channel_id': self.id,
                                      'account_id': account.id, 'external_key': account.external_account_key})
        if not self.setup_policy_id:
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        self.invalidate_recordset()
        return True

    def action_slack_enable_replies(self):
        self._require_slack_setup()
        sender,generation=self.selected_sender_id,self.generation
        if not sender or sender!=self.setup_sender_id or not sender._check_health():
            raise UserError(_('Finish setup and verify the connected sender first.'))
        self._lock()
        self.invalidate_recordset()
        if (self.selected_sender_id!=sender or self.generation!=generation or self.setup_completed_steps!=5
                or not self._is_setup_receiving_ready() or not self.slack_test_received
                or self.sudo().slack_test_fingerprint!=self._slack_test_fingerprint()
                or not self.approval_type_id.active or self.approval_type_id.company_id!=self.company_id):
            raise UserError(_('Complete setup and select an active message approval policy for this company.'))
        internal(self).write({'dispatch_enabled':True})
        self._audit('slack.approved_replies_enabled',_('Approved private text replies enabled. Recipient consent and message approval remain required.'))
        return True
