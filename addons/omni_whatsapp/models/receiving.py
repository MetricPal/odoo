"""Scoped callback preparation and explicit intake authorization, WhatsApp only."""
import re
import secrets
from urllib.parse import urlsplit

from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import valid_callback_url

from ..providers import vault
from ..providers.webhook import verification_challenge

CHECK_FIELDS = {'whatsapp_verified_reference', 'whatsapp_verified_url', 'whatsapp_callback_checked_at'}


def same_callback(left, right):
    def key(url):
        parsed = urlsplit(url)
        return (parsed.scheme, (parsed.hostname or '').encode('idna').decode().lower(),
                parsed.port or 443, parsed.path)
    return key(left) == key(right)


def retire_unused(registry, references):
    # Commit callbacks survive nested savepoint rollbacks in Odoo 20.
    # Recheck committed references before deleting ANY encrypted file.
    with registry.cursor() as cr:
        accounts = api.Environment(cr, SUPERUSER_ID, {})['omni.account'].with_context(active_test=False)
        for reference in references:
            if not accounts.search_count([('credential_reference', '=', reference)]):
                vault.remove(reference, cr.dbname)


class WhatsAppAccount(models.Model):
    _inherit = 'omni.account'

    def _adapter_config(self):
        result = super()._adapter_config()
        if self.channel_type_id.code == 'whatsapp':
            result.update(database=self.env.cr.dbname, company_id=self.company_id.id,
                          purpose_id=self.purpose_id.id, business_account_id=self.whatsapp_business_id)
        return result


class WhatsAppEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    whatsapp_verified_reference = fields.Char(readonly=True, copy=False, groups='base.group_no_one')
    whatsapp_verified_url = fields.Char(readonly=True, copy=False)
    whatsapp_callback_checked_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, CHECK_FIELDS, vals_list):
            raise AccessError(_('Webhook verification is server-managed.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, CHECK_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_('Webhook verification is server-managed.'))
        if 'webhook_url_override' in values:
            self._require_manager()  # Authorize before any elevated verification-state write.
            for endpoint in self.filtered(lambda e: e.channel_type_id.code == 'whatsapp'):
                if values['webhook_url_override'] and not valid_callback_url(values['webhook_url_override'], endpoint.route_key):
                    raise UserError(_('Use your public HTTPS URL and keep the channel path.'))
                if values['webhook_url_override'] != endpoint.webhook_url_override:
                    endpoint.channel_id._whatsapp_before_connection_change()
                    internal(endpoint.sudo()).write({'whatsapp_verified_reference': False,
                        'whatsapp_verified_url': False, 'whatsapp_callback_checked_at': False,
                        'state': 'disabled', 'health': 'unchecked'})
                    endpoint.channel_id._whatsapp_invalidate_receiving()
        return super().write(values)

    def _whatsapp_verified(self):
        self.ensure_one()
        endpoint = self.sudo()
        return bool(endpoint.whatsapp_callback_checked_at
                    and endpoint.whatsapp_verified_reference == endpoint.account_id.credential_reference
                    and endpoint.whatsapp_verified_url == endpoint._get_webhook_url())

    def _config(self):
        result = super()._config()
        if self.channel_type_id.code == 'whatsapp':
            result['whatsapp_callback_verified'] = self._whatsapp_verified()
        return result

    def _allowed(self, policy=None):
        result = super()._allowed(policy)
        return result and (self.channel_type_id.code != 'whatsapp' or self._whatsapp_verified())

    def _whatsapp_challenge(self, parameters, callback_url):
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_('Only verified transport may confirm a callback.'))
        self.channel_id._lock()
        self.invalidate_recordset()
        self.account_id.invalidate_recordset()
        if (self.channel_type_id.code != 'whatsapp' or not self.active or not self.channel_id.active
                or not self.account_id.active or not same_callback(callback_url, self._get_webhook_url() or '')):
            raise ValueError('verification')
        from ..providers.adapter import bundle
        credentials = bundle(self._config())
        challenge = verification_challenge(parameters, credentials.get('verify_token'))
        if not credentials.get('app_secret'):
            raise ValueError('verification')
        internal(self).write({'whatsapp_verified_reference': self.account_id.credential_reference,
                             'whatsapp_verified_url': self._get_webhook_url(),
                             'whatsapp_callback_checked_at': fields.Datetime.now()})
        return challenge


class WhatsAppChannel(models.Model):
    _inherit = 'omni.channel'

    whatsapp_receiving_ui = fields.Json(compute='_compute_whatsapp_receiving_ui',
                                        groups='omni_channel.group_omni_manager')

    def _whatsapp_invalidate_receiving(self):
        self.ensure_one()
        completed = [step for step in self._completed_setup_steps() if step < 2]
        internal(self).write({'setup_completed_step_ids': completed,
                             'setup_completed_steps': len(completed), 'setup_receiving_deferred': False})

    @api.depends('setup_endpoint_id', 'setup_endpoint_id.whatsapp_callback_checked_at',
                 'setup_endpoint_id.webhook_url_override', 'setup_account_id.credential_reference',
                 'setup_endpoint_state')
    def _compute_whatsapp_receiving_ui(self):
        for channel in self:
            channel.whatsapp_receiving_ui = {}
            if not channel.is_whatsapp or not channel.setup_endpoint_id:
                continue
            credentials = channel.setup_account_id._whatsapp_credentials()
            endpoint = channel.setup_endpoint_id
            channel.whatsapp_receiving_ui = {
                'url': endpoint._get_webhook_url() or
                    'https://channels.example.com/omni/inbound/' + endpoint.route_key,
                'token': credentials.get('verify_token', ''),
                'saved': bool(credentials.get('app_secret')), 'verified': endpoint._whatsapp_verified(),
                'enabled': endpoint.state == 'enabled',
            }

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_whatsapp:
            return super().action_setup_prepare_connection()
        result = super().action_setup_prepare_connection()
        self._lock()
        self.invalidate_recordset()
        account = self.setup_account_id
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            if self.env[model].sudo().with_context(active_test=False).search_count([
                    ('account_id', '=', account.id), ('channel_id', '!=', self.id)]):
                raise UserError(_('This phone number already belongs to another channel.'))
        if not self.setup_endpoint_id:
            self.env['omni.inbound.endpoint'].create({'name': self.name, 'channel_id': self.id,
                'account_id': account.id, 'external_key': account.external_account_key})
        if not self.setup_sender_id:
            self.env['omni.outbound.sender'].create({'name': self.name, 'channel_id': self.id,
                'account_id': account.id, 'external_key': account.external_account_key})
        if not self.setup_policy_id:
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        credentials = account._whatsapp_credentials()
        if not credentials.get('verify_token'):
            reference, previous = self._whatsapp_replace_bundle({**credentials, 'verify_token': secrets.token_urlsafe(32)})
            registry = self.env.registry
            self.env.cr.postcommit.add(lambda: retire_unused(registry, (previous, reference)))
        self.invalidate_recordset()
        return result

    def _whatsapp_replace_bundle(self, credentials):
        account = self.setup_account_id
        previous = account.credential_reference
        reference = vault.store(credentials)
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        try:
            internal(account).write({'credential_reference': reference})
        except Exception:
            vault.remove(reference, database)
            raise
        return reference, previous

    def action_whatsapp_save_webhook(self, callback_url, app_secret=''):
        self._require_whatsapp_setup()
        self._lock()
        self.invalidate_recordset()
        endpoint = self.setup_endpoint_id
        if not endpoint:
            raise UserError(_('Complete Credentials first.'))
        if (not isinstance(callback_url, str) or 'channels.example.com' in callback_url
                or not valid_callback_url(callback_url, endpoint.route_key)):
            raise UserError(_('Use your public HTTPS URL and keep the channel path.'))
        credentials = self.setup_account_id._whatsapp_credentials()
        if not isinstance(app_secret, str) or (app_secret and not re.fullmatch(r'[0-9a-fA-F]{32}', app_secret)):
            raise UserError(_('Enter the app secret from Meta app settings.'))
        if not app_secret and not credentials.get('app_secret'):
            raise UserError(_('Enter the app secret from Meta app settings.'))
        replacement = None
        try:
            with self.env.cr.savepoint():
                if app_secret and app_secret != credentials.get('app_secret'):
                    self._whatsapp_before_connection_change()
                    replacement = self._whatsapp_replace_bundle({**credentials, 'app_secret': app_secret})
                    internal(endpoint.sudo()).write({'whatsapp_verified_reference': False,
                        'whatsapp_verified_url': False, 'whatsapp_callback_checked_at': False,
                        'state': 'disabled', 'health': 'unchecked'})
                    self._whatsapp_invalidate_receiving()
                endpoint.write({'webhook_url_override': callback_url})
                self._audit('whatsapp.webhook_saved', str(endpoint.id))
        except Exception:
            if replacement:
                vault.remove(replacement[0], self.env.cr.dbname)
            raise
        if replacement:
            registry = self.env.registry
            self.env.cr.postcommit.add(lambda: retire_unused(registry, replacement))
        return True

    def action_setup_defer_receiving(self):
        self.ensure_one()
        if self.is_whatsapp:
            self._require_whatsapp_setup()
            raise UserError(_('Enable receiving before continuing.'))
        return super().action_setup_defer_receiving()

    def action_setup_validate_step(self, step):
        self.ensure_one()
        return super().action_setup_validate_step(step)
