"""Discord channel setup: bot verification, relay secret and the server channels to read."""

import re
import secrets

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import valid_callback_url

from ..providers import rest, vault

PROFILE_FIELDS = {'discord_bot_name', 'discord_verified_at', 'discord_channel_ids'}
MAX_CHANNELS = 20


def retire_unused(registry, references):
    with registry.cursor() as cr:
        accounts = api.Environment(cr, SUPERUSER_ID, {})['omni.account'].with_context(active_test=False)
        for reference in references:
            if reference and not accounts.search_count([('credential_reference', '=', reference)]):
                vault.remove(reference, cr.dbname)


def parse_channels(text):
    ids = [part for part in re.split(r'[\s,;]+', text or '') if part]
    if len(ids) > MAX_CHANNELS or any(not rest.snowflake(i) for i in ids):
        raise UserError(_('Enter up to %(count)s Discord channel IDs (numbers), separated by commas.', count=MAX_CHANNELS))
    return sorted(set(ids))


class DiscordAccount(models.Model):
    _inherit = 'omni.account'

    discord_bot_name = fields.Char(readonly=True, copy=False, string='Bot')
    discord_verified_at = fields.Datetime(readonly=True, copy=False)
    discord_channel_ids = fields.Char(readonly=True, copy=False, string='Server channels')

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, PROFILE_FIELDS, vals_list) and not is_internal(self):
            raise AccessError(_('Discord details are recorded by setup.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, PROFILE_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_('Discord details are recorded by setup.'))
        return super().write(values)

    def _adapter_config(self):
        result = super()._adapter_config()
        if self.channel_type_id.code == 'discord':
            result.update(database=self.env.cr.dbname, company_id=self.company_id.id, purpose_id=self.purpose_id.id,
                          channels=(self.discord_channel_ids or '').split(',') if self.discord_channel_ids else [])
        return result

    def _discord_credentials(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'discord' or not self.active or not self.discord_verified_at:
            raise UserError(_('Connect the Discord bot first.'))
        try:
            return vault.load(self.credential_reference, database=self.env.cr.dbname, company_id=self.company_id.id,
                              purpose_id=self.purpose_id.id, bot_id=self.external_account_key)
        except Exception:
            raise UserError(_('The saved bot credentials could not be read.')) from None


class DiscordEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    def _allowed(self, policy=None):
        result = super()._allowed(policy)
        if not result or self.channel_type_id.code != 'discord':
            return result
        try:
            from ..providers.adapter import bundle
            return bool(bundle(self._config()).get('relay_secret'))
        except Exception:  # noqa: BLE001
            return False


class DiscordChannel(models.Model):
    _inherit = 'omni.channel'

    is_discord = fields.Boolean(compute='_compute_is_discord')
    discord_credentials_ui = fields.Json(compute='_compute_discord_ui', groups='omni_channel.group_omni_manager')
    discord_receiving_ui = fields.Json(compute='_compute_discord_ui', groups='omni_channel.group_omni_manager')

    @api.depends('channel_type_id.code')
    def _compute_is_discord(self):
        for channel in self:
            channel.is_discord = channel.channel_type_id.code == 'discord'

    # Display-only: recomputed on every read, so endpoint changes need no dependency.
    @api.depends('setup_account_id', 'setup_account_id.discord_verified_at', 'setup_account_id.discord_channel_ids')
    def _compute_discord_ui(self):
        for channel in self:
            account = channel.setup_account_id
            channel.discord_credentials_ui = (
                {'bot': account.external_account_key, 'name': account.discord_bot_name}
                if channel.is_discord and account.discord_verified_at else {}
            )
            channel.discord_receiving_ui = {}
            endpoint = channel.setup_endpoint_id
            if channel.is_discord and endpoint and account.discord_verified_at:
                credentials = account._discord_credentials()
                url = endpoint._get_webhook_url() or ''
                secret = credentials.get('relay_secret', '')
                channel.discord_receiving_ui = {
                    'url': url,
                    'secret': secret,
                    'channels': account.discord_channel_ids or '',
                    'enabled': endpoint.state == 'enabled',
                    'command': (
                        'DISCORD_BOT_TOKEN=<bot token> OMNI_RELAY_SECRET=%s python3 addons/omni_discord/tools/'
                        'discord_relay.py --url %s --bot %s' % (secret, url or '<public URL>', account.external_account_key)
                    ) if secret else '',
                }

    def _require_discord_setup(self):
        self.ensure_one()
        self._require_manager()
        self._check_scope()
        if not self.active or not self.is_discord:
            raise UserError(_('Choose an active Discord channel.'))

    def action_discord_save_connection(self, bot_token):
        self._require_discord_setup()
        if self.setup_account_id:
            raise UserError(_('This channel already has a saved connection.'))
        try:
            bot_id, name = rest.bot(bot_token)
        except rest.RestError as error:
            messages = {
                'not_bot': _('This token does not belong to a bot. Copy the token from Developer Portal › Bot.'),
                'unauthorized': _('Discord refused the token. Reset it in the Developer Portal and paste the new one.'),
                'rate_limited': _('Discord is busy. Please try again shortly.'),
            }
            raise UserError(messages.get(error.code, _('Could not reach Discord. Please try again.'))) from None
        self._lock()
        self.invalidate_recordset(['setup_account_id', 'sender_ids', 'endpoint_ids'])
        if self.setup_account_id or self.sender_ids or self.endpoint_ids:
            raise UserError(_('This channel already has a saved connection.'))
        reference = vault.store({'database': self.env.cr.dbname, 'company_id': self.company_id.id,
                                 'purpose_id': self.purpose_id.id, 'bot_id': bot_id, 'bot_token': bot_token})
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        account = internal(self.env['omni.account']).create({
            'name': name, 'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
            'channel_type_id': self.channel_type_id.id, 'external_account_key': bot_id, 'namespace': bot_id,
            'credential_reference': reference, 'discord_bot_name': name, 'discord_verified_at': fields.Datetime.now(),
        })
        self.write({'setup_account_id': account.id})
        self._audit('discord.credentials_verified', str(account.id))
        return {'bot': bot_id, 'name': name}

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_discord:
            return super().action_setup_prepare_connection()
        self._require_discord_setup()
        self._check_setup_account()
        account = self.setup_account_id
        if not account:
            raise UserError(_('Connect the Discord bot first.'))
        credentials = account._discord_credentials()
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            if self.env[model].sudo().with_context(active_test=False).search_count([
                    ('account_id', '=', account.id), ('channel_id', '!=', self.id)]):
                raise UserError(_('This bot already belongs to another channel.'))
        values = {'name': self.name, 'channel_id': self.id, 'account_id': account.id,
                  'external_key': account.external_account_key}
        if not self.setup_endpoint_id:
            self.env['omni.inbound.endpoint'].create(values)
        if not self.setup_sender_id:
            self.env['omni.outbound.sender'].create(values)
        if not self.setup_policy_id:
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        if not credentials.get('relay_secret'):
            previous = account.credential_reference
            reference = vault.store({**credentials, 'relay_secret': secrets.token_urlsafe(48)})
            database = self.env.cr.dbname
            self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
            internal(account).write({'credential_reference': reference})
            registry = self.env.registry
            self.env.cr.postcommit.add(lambda: retire_unused(registry, (previous,)))
        self.invalidate_recordset()
        return True

    def action_discord_save_receiving(self, callback_url, channel_ids):
        """Keep the relay's target URL and the server channels the bot may read and answer in."""
        self._require_discord_setup()
        self._lock()
        endpoint = self.setup_endpoint_id
        if not endpoint:
            raise UserError(_('Complete Credentials first.'))
        if not valid_callback_url(callback_url, endpoint.route_key):
            raise UserError(_('Use your public HTTPS URL and keep the channel path.'))
        ids = parse_channels(channel_ids)
        internal(self.setup_account_id).write({'discord_channel_ids': ','.join(ids)})
        endpoint.write({'webhook_url_override': callback_url})
        self._audit('discord.receiving_saved', str(endpoint.id))
        return True
