"""Teams-only setup through existing scoped Odoo records and public actions."""

import re
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import valid_callback_url
from ..providers import api as teams, vault

PROFILE = {'teams_tenant_id', 'teams_verified_at'}


class TeamsAccount(models.Model):
    _inherit = 'omni.account'

    teams_tenant_id = fields.Char(readonly=True, copy=False)
    teams_verified_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, PROFILE, vals_list) and not is_internal(self):
            raise AccessError(_('Teams details are recorded by verification.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, PROFILE, [values]) and not is_internal(self):
            raise AccessError(_('Teams details are recorded by verification.'))
        return super().write(values)

    def _teams_credentials(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'teams' or not self.active or not self.teams_verified_at:
            raise UserError(_('Verify the Teams app first.'))
        try:
            return vault.load(
                self.credential_reference,
                database=self.env.cr.dbname,
                company_id=self.company_id.id,
                purpose_id=self.purpose_id.id,
                app_id=self.external_account_key,
                tenant_id=self.teams_tenant_id,
            )
        except Exception:
            raise UserError(_('Saved Teams credentials are unavailable.')) from None

    def _adapter_config(self):
        result = super()._adapter_config()
        if self.channel_type_id.code == 'teams':
            result.update(
                database=self.env.cr.dbname,
                company_id=self.company_id.id,
                purpose_id=self.purpose_id.id,
                tenant_id=self.teams_tenant_id,
            )
        return result


class TeamsEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    def write(self, values):
        if 'webhook_url_override' in values:
            self._require_manager()
            for endpoint in self.filtered(lambda e: e.channel_type_id.code == 'teams'):
                value = values['webhook_url_override']
                if value and not valid_callback_url(value, endpoint.route_key):
                    raise UserError(_('Use a public HTTPS URL and keep the channel path.'))
                if value != endpoint.webhook_url_override:
                    endpoint.channel_id._teams_before_connection_change()
                    internal(endpoint.sudo()).write({'state': 'disabled', 'health': 'unchecked'})
                    completed = [s for s in endpoint.channel_id._completed_setup_steps() if s < 2]
                    internal(endpoint.channel_id).write(
                        {'setup_completed_step_ids': completed, 'setup_completed_steps': len(completed)}
                    )
        return super().write(values)

    def _config(self):
        result = super()._config()
        if self.channel_type_id.code == 'teams':
            result['teams_callback_url'] = self._get_webhook_url()
        return result


class TeamsChannel(models.Model):
    _inherit = 'omni.channel'

    is_teams = fields.Boolean(compute='_compute_is_teams')
    teams_credentials_ui = fields.Json(
        compute='_compute_teams_credentials_ui', groups='omni_channel.group_omni_manager'
    )

    @api.depends('channel_type_id.code')
    def _compute_is_teams(self):
        for channel in self:
            channel.is_teams = channel.channel_type_id.code == 'teams'

    @api.depends('setup_account_id')
    def _compute_teams_credentials_ui(self):
        for channel in self:
            account = channel.setup_account_id
            channel.teams_credentials_ui = (
                {'name': account.name, 'tenant': account.teams_tenant_id}
                if channel.is_teams and account.teams_verified_at
                else {}
            )

    def _require_teams_setup(self):
        self.ensure_one()
        self._require_manager()
        self._check_scope()
        if not self.active or not self.is_teams:
            raise UserError(_('Choose an active Teams channel.'))

    def action_teams_connect(self, app_id, tenant_id, secret):
        self._require_teams_setup()
        scope = (self.company_id.id, self.purpose_id.id, self.channel_type_id.id)
        try:
            teams.token(tenant_id, app_id, secret)
        except Exception:
            raise UserError(_('Check the bot app ID, tenant ID and client secret.')) from None
        self._lock()
        self.invalidate_recordset()
        self._require_teams_setup()
        if (
            scope != (self.company_id.id, self.purpose_id.id, self.channel_type_id.id)
            or self.setup_account_id
            or self.sender_ids
            or self.endpoint_ids
        ):
            raise UserError(_('This channel changed or already has a connection.'))
        credentials = {
            'database': self.env.cr.dbname,
            'company_id': self.company_id.id,
            'purpose_id': self.purpose_id.id,
            'tenant_id': tenant_id,
            'app_id': app_id,
            'secret': secret,
        }
        reference = vault.store(credentials)
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        try:
            with self.env.cr.savepoint():
                account = internal(self.env['omni.account']).create(
                    {
                        'name': self.name,
                        'company_id': self.company_id.id,
                        'purpose_id': self.purpose_id.id,
                        'channel_type_id': self.channel_type_id.id,
                        'external_account_key': app_id,
                        'namespace': tenant_id,
                        'credential_reference': reference,
                        'teams_tenant_id': tenant_id,
                        'teams_verified_at': fields.Datetime.now(),
                    }
                )
                self.write({'setup_account_id': account.id})
                self.action_setup_prepare_connection()
                self._audit('teams.credentials_verified', str(account.id))
        except Exception:
            vault.remove(reference, database)
            raise
        return True

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_teams:
            return super().action_setup_prepare_connection()
        self._require_teams_setup()
        self._check_setup_account()
        self._lock()
        self.invalidate_recordset()
        account = self.setup_account_id
        if not account:
            raise UserError(_('Connect the Teams app first.'))
        account._teams_credentials()
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            if (
                self.env[model]
                .sudo()
                .with_context(active_test=False)
                .search_count([('account_id', '=', account.id), ('channel_id', '!=', self.id)])
            ):
                raise UserError(_('This Teams app is already assigned to another channel.'))
            bindings = self.sender_ids if model == 'omni.outbound.sender' else self.endpoint_ids
            if not bindings:
                self.env[model].create(
                    {
                        'name': self.name,
                        'channel_id': self.id,
                        'account_id': account.id,
                        'external_key': account.external_account_key,
                    }
                )
        if not self.setup_policy_id:
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        self.invalidate_recordset()
        return True

    def action_teams_enable_replies(self):
        self._require_teams_setup()
        sender, generation = self.selected_sender_id, self.generation
        if not sender or sender != self.setup_sender_id or not sender._check_health():
            raise UserError(_('Finish setup and verify the connected sender first.'))
        self._lock()
        self.invalidate_recordset()
        if (
            self.selected_sender_id != sender
            or self.generation != generation
            or self.setup_completed_steps != 5
            or not self._is_setup_receiving_ready()
            or not self.teams_test_received
            or self.sudo().teams_test_fingerprint != self._teams_test_fingerprint()
            or not self.approval_type_id.active
            or self.approval_type_id.company_id != self.company_id
        ):
            raise UserError(_('Complete setup and select an active message approval policy for this company.'))
        internal(self).write({'dispatch_enabled': True})
        self._audit(
            'teams.approved_replies_enabled',
            _('Approved private text replies enabled. Recipient consent and message approval remain required.'),
        )
        return True
