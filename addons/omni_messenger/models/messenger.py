"""Messenger channel setup: Page connection, signed receiving and approved replies.

Mirrors the WhatsApp flow: the Page token is verified with Meta and kept in
the encrypted vault; receiving needs the app secret and a verified webhook
handshake before the endpoint can be enabled. Replies go through the normal
Omnichannel review and dispatch.
"""

import re
import secrets
from urllib.parse import urlsplit

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import valid_callback_url

from ..providers import graph, vault
from ..providers.webhook import verification_challenge

PROFILE_FIELDS = {'messenger_page_name', 'messenger_verified_at'}
CHECK_FIELDS = {'messenger_verified_reference', 'messenger_verified_url', 'messenger_callback_checked_at'}


def same_callback(left, right):
    def key(url):
        parsed = urlsplit(url)
        return (parsed.scheme, (parsed.hostname or '').encode('idna').decode().lower(), parsed.port or 443, parsed.path)
    return key(left) == key(right)


def retire_unused(registry, references):
    with registry.cursor() as cr:
        accounts = api.Environment(cr, SUPERUSER_ID, {})['omni.account'].with_context(active_test=False)
        for reference in references:
            if reference and not accounts.search_count([('credential_reference', '=', reference)]):
                vault.remove(reference, cr.dbname)


class MessengerAccount(models.Model):
    _inherit = 'omni.account'

    messenger_page_name = fields.Char(readonly=True, copy=False, string='Page')
    messenger_verified_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, PROFILE_FIELDS, vals_list) and not is_internal(self):
            raise AccessError(_('Messenger details are recorded by Page verification.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, PROFILE_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_('Messenger details are recorded by Page verification.'))
        return super().write(values)

    def _adapter_config(self):
        result = super()._adapter_config()
        if self.channel_type_id.code == 'messenger':
            result.update(database=self.env.cr.dbname, company_id=self.company_id.id, purpose_id=self.purpose_id.id)
        return result

    def _messenger_credentials(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'messenger' or not self.active or not self.messenger_verified_at:
            raise UserError(_('Connect the Facebook Page first.'))
        try:
            return vault.load(self.credential_reference, database=self.env.cr.dbname, company_id=self.company_id.id,
                              purpose_id=self.purpose_id.id, page_id=self.external_account_key)
        except Exception:
            raise UserError(_('The saved Page credentials could not be read.')) from None


class MessengerEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    messenger_verified_reference = fields.Char(readonly=True, copy=False, groups='base.group_no_one')
    messenger_verified_url = fields.Char(readonly=True, copy=False)
    messenger_callback_checked_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, CHECK_FIELDS, vals_list):
            raise AccessError(_('Webhook verification is server-managed.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, CHECK_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_('Webhook verification is server-managed.'))
        if 'webhook_url_override' in values:
            self._require_manager()
            for endpoint in self.filtered(lambda e: e.channel_type_id.code == 'messenger'):
                if values['webhook_url_override'] and not valid_callback_url(values['webhook_url_override'], endpoint.route_key):
                    raise UserError(_('Use your public HTTPS URL and keep the channel path.'))
                if values['webhook_url_override'] != endpoint.webhook_url_override:
                    internal(endpoint.sudo()).write({
                        'messenger_verified_reference': False, 'messenger_verified_url': False,
                        'messenger_callback_checked_at': False, 'state': 'disabled', 'health': 'unchecked',
                    })
        return super().write(values)

    def _messenger_verified(self):
        self.ensure_one()
        endpoint = self.sudo()
        return bool(endpoint.messenger_callback_checked_at
                    and endpoint.messenger_verified_reference == endpoint.account_id.credential_reference
                    and endpoint.messenger_verified_url == endpoint._get_webhook_url())

    def _config(self):
        result = super()._config()
        if self.channel_type_id.code == 'messenger':
            result['messenger_callback_verified'] = self._messenger_verified()
        return result

    def _allowed(self, policy=None):
        result = super()._allowed(policy)
        return result and (self.channel_type_id.code != 'messenger' or self._messenger_verified())

    def _messenger_challenge(self, parameters, callback_url):
        """Called by Omnichannel's GET handshake route (as superuser)."""
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_('Only verified transport may confirm a callback.'))
        self.channel_id._lock()
        self.invalidate_recordset()
        self.account_id.invalidate_recordset()
        if (self.channel_type_id.code != 'messenger' or not self.active or not self.channel_id.active
                or not self.account_id.active or not same_callback(callback_url, self._get_webhook_url() or '')):
            raise ValueError('verification')
        from ..providers.adapter import bundle
        credentials = bundle(self._config())
        challenge = verification_challenge(parameters, credentials.get('verify_token'))
        if not credentials.get('app_secret'):
            raise ValueError('verification')
        internal(self).write({'messenger_verified_reference': self.account_id.credential_reference,
                              'messenger_verified_url': self._get_webhook_url(),
                              'messenger_callback_checked_at': fields.Datetime.now()})
        return challenge


class MessengerChannel(models.Model):
    _inherit = 'omni.channel'

    is_messenger = fields.Boolean(compute='_compute_is_messenger')
    messenger_credentials_ui = fields.Json(compute='_compute_messenger_ui', groups='omni_channel.group_omni_manager')
    messenger_receiving_ui = fields.Json(compute='_compute_messenger_ui', groups='omni_channel.group_omni_manager')

    @api.depends('channel_type_id.code')
    def _compute_is_messenger(self):
        for channel in self:
            channel.is_messenger = channel.channel_type_id.code == 'messenger'

    # Display-only: recomputed on every read, so endpoint changes need no dependency.
    @api.depends('setup_account_id', 'setup_account_id.messenger_verified_at')
    def _compute_messenger_ui(self):
        for channel in self:
            account = channel.setup_account_id
            channel.messenger_credentials_ui = (
                {'page': account.external_account_key, 'name': account.messenger_page_name}
                if channel.is_messenger and account.messenger_verified_at else {}
            )
            channel.messenger_receiving_ui = {}
            endpoint = channel.setup_endpoint_id
            if channel.is_messenger and endpoint and account.messenger_verified_at:
                credentials = account._messenger_credentials()
                channel.messenger_receiving_ui = {
                    'url': endpoint._get_webhook_url() or 'https://channels.example.com/omni/inbound/' + endpoint.route_key,
                    'token': credentials.get('verify_token', ''),
                    'saved': bool(credentials.get('app_secret')),
                    'verified': endpoint._messenger_verified(),
                    'enabled': endpoint.state == 'enabled',
                }

    def _require_messenger_setup(self):
        self.ensure_one()
        self._require_manager()
        self._check_scope()
        if not self.active or not self.is_messenger:
            raise UserError(_('Choose an active Messenger channel.'))

    def action_messenger_save_connection(self, page_token):
        """Verify a Page access token with Meta and keep it in the vault."""
        self._require_messenger_setup()
        if self.setup_account_id:
            raise UserError(_('This channel already has a saved connection.'))
        try:
            page_id, page_name = graph.page(page_token)
        except graph.GraphError as error:
            messages = {
                'page_token': _('This is not a Page access token. Generate one for the Page in Meta for Developers.'),
                'unauthorized': _('Meta refused the token. Check that it is current and has Messenger permissions.'),
                'rate_limited': _('Meta is busy. Please try again later.'),
            }
            raise UserError(messages.get(error.code, _('Could not reach Meta. Please try again.'))) from None
        self._lock()
        self.invalidate_recordset(['setup_account_id', 'sender_ids', 'endpoint_ids'])
        if self.setup_account_id or self.sender_ids or self.endpoint_ids:
            raise UserError(_('This channel already has a saved connection.'))
        bundle = {'database': self.env.cr.dbname, 'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
                  'page_id': page_id, 'access_token': page_token, 'verify_token': secrets.token_urlsafe(32)}
        reference = vault.store(bundle)
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        account = internal(self.env['omni.account']).create({
            'name': page_name, 'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
            'channel_type_id': self.channel_type_id.id, 'external_account_key': page_id, 'namespace': page_id,
            'credential_reference': reference, 'messenger_page_name': page_name,
            'messenger_verified_at': fields.Datetime.now(),
        })
        self.write({'setup_account_id': account.id})
        self._audit('messenger.credentials_verified', str(account.id))
        return {'page': page_id, 'name': page_name}

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_messenger:
            return super().action_setup_prepare_connection()
        self._require_messenger_setup()
        self._check_setup_account()
        account = self.setup_account_id
        if not account:
            raise UserError(_('Connect the Facebook Page first.'))
        account._messenger_credentials()
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            if self.env[model].sudo().with_context(active_test=False).search_count([
                    ('account_id', '=', account.id), ('channel_id', '!=', self.id)]):
                raise UserError(_('This Page already belongs to another channel.'))
        values = {'name': self.name, 'channel_id': self.id, 'account_id': account.id,
                  'external_key': account.external_account_key}
        if not self.setup_endpoint_id:
            self.env['omni.inbound.endpoint'].create(values)
        if not self.setup_sender_id:
            self.env['omni.outbound.sender'].create(values)
        if not self.setup_policy_id:
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        self.invalidate_recordset()
        return True

    def action_messenger_save_webhook(self, callback_url, app_secret=''):
        self._require_messenger_setup()
        self._lock()
        self.invalidate_recordset()
        endpoint = self.setup_endpoint_id
        if not endpoint:
            raise UserError(_('Complete Credentials first.'))
        if (not isinstance(callback_url, str) or 'channels.example.com' in callback_url
                or not valid_callback_url(callback_url, endpoint.route_key)):
            raise UserError(_('Use your public HTTPS URL and keep the channel path.'))
        account = self.setup_account_id
        credentials = account._messenger_credentials()
        if not isinstance(app_secret, str) or (app_secret and not re.fullmatch(r'[0-9a-fA-F]{32}', app_secret)):
            raise UserError(_('Enter the app secret from Meta app settings (32 characters).'))
        if not app_secret and not credentials.get('app_secret'):
            raise UserError(_('Enter the app secret from Meta app settings (32 characters).'))
        if app_secret and app_secret != credentials.get('app_secret'):
            previous = account.credential_reference
            reference = vault.store({**credentials, 'app_secret': app_secret})
            database = self.env.cr.dbname
            self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
            internal(account).write({'credential_reference': reference})
            internal(endpoint.sudo()).write({'messenger_verified_reference': False, 'messenger_verified_url': False,
                                             'messenger_callback_checked_at': False, 'state': 'disabled',
                                             'health': 'unchecked'})
            registry = self.env.registry
            self.env.cr.postcommit.add(lambda: retire_unused(registry, (previous,)))
        endpoint.write({'webhook_url_override': callback_url})
        self._audit('messenger.webhook_saved', str(endpoint.id))
        return True

    def action_setup_defer_receiving(self):
        self.ensure_one()
        if self.is_messenger:
            self._require_messenger_setup()
            raise UserError(_('Turn on receiving first: replies are possible only to people who wrote to the Page.'))
        return super().action_setup_defer_receiving()
