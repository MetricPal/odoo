import re
import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.models.inbox import lock_company
from odoo.addons.omni_channel.providers.base import get_adapter
from odoo.addons.omni_telegram.providers.secrets import (
    TelegramConfigurationError,
    canonical_id,
    discover_bot_id,
    resolve,
)

from odoo.addons.omni_telegram.providers.test_message import TEST_MESSAGE, send_test_message
from odoo.addons.omni_telegram.providers import runtime_secrets
from odoo.addons.omni_telegram.providers.setup import TelegramSetupError, prepare_credentials, verify_webhook, webhook_info, register_webhook


def verification_retry(record, method, error):
    """Transient checks return a retry action without changing verification history."""
    messages = {
        'transport': _("Couldn’t reach Telegram. Please try again."),
        'unavailable': _("Telegram is temporarily unavailable. Please try again shortly."),
        'rate_limit': _("Telegram is receiving too many requests. Please wait before retrying."),
    }
    if error.reason not in messages:
        return None
    details = {
        'transport': _("The HTTPS request to api.telegram.org did not complete. The exact cause was not identified. If retries keep failing, check server DNS, outbound HTTPS, TLS certificates and timeouts. This does not mean the bot token is invalid."),
        'unavailable': _("Telegram returned a server error. Retry later. Your saved credentials and last successful verification have not changed."),
        'rate_limit': _("Telegram returned HTTP 429 (too many requests). No automatic retry was made. Your saved credentials and last successful verification have not changed."),
    }
    return {'type': 'ir.actions.client', 'tag': 'omni_telegram.verification_retry', 'params': {
        'model': record._name, 'record_id': record.id, 'method': method,
        'message': messages[error.reason], 'details': details[error.reason],
    }}


class TelegramAccount(models.Model):
    _inherit = "omni.account"

    # Non-stored, write-only inputs: ORM reads always return an empty value.
    telegram_bot_token = fields.Char(
        string="Bot token", compute="_compute_credential_inputs", inverse="_inverse_credential_inputs",
        groups="omni_channel.group_omni_manager", copy=False,
    )
    telegram_webhook_secret = fields.Char(
        string="Webhook secret", compute="_compute_credential_inputs", inverse="_inverse_credential_inputs",
        groups="omni_channel.group_omni_manager", copy=False,
        help="Leave blank to generate a secret for a new connection, or keep the existing secret when replacing a token.",
    )
    telegram_bot_name = fields.Char(readonly=True, copy=False)
    telegram_bot_username = fields.Char(readonly=True, copy=False)
    telegram_verified_at = fields.Datetime(string="Bot verified at", readonly=True, copy=False)
    telegram_has_credentials = fields.Boolean(compute="_compute_has_credentials")
    is_telegram = fields.Boolean(compute="_compute_is_telegram")

    def _compute_credential_inputs(self):
        for record in self:
            record.telegram_bot_token = False
            record.telegram_webhook_secret = False

    def _inverse_credential_inputs(self):
        # create/write consume these inputs before the ORM can cache them.
        pass

    @api.depends("credential_reference")
    def _compute_has_credentials(self):
        for record in self:
            record.telegram_has_credentials = bool(record.sudo().credential_reference)

    @api.model
    def _prepare_runtime_credentials(self, values, existing=None):
        values = dict(values)
        token = values.pop('telegram_bot_token', False)
        secret = values.pop('telegram_webhook_secret', False)
        if not token and not secret:
            return values, None
        self.check_access('write' if existing else 'create')
        if not self.env.user.has_group('omni_channel.group_omni_manager'):
            raise AccessError(_('Only an Omni administrator can configure a bot.'))
        company_id = values.get('company_id') or (existing.company_id.id if existing else self.env.context.get('default_company_id') or self.env.company.id)
        purpose_id = values.get('purpose_id') or (existing.purpose_id.id if existing else self.env.context.get('default_purpose_id'))
        type_id = values.get('channel_type_id') or (existing.channel_type_id.id if existing else self.env.context.get('default_channel_type_id'))
        if company_id not in self.env.companies.ids:
            raise AccessError(_('Select an allowed company before configuring the bot.'))
        purpose = self.env['omni.purpose'].browse(purpose_id).exists()
        purpose.check_access('read')
        if not purpose or (not self.env.user.has_group('base.group_system') and self.env.user not in purpose.user_ids):
            raise AccessError(_('Select an authorized communication team.'))
        channel_type = self.env['omni.channel.type'].browse(type_id)
        channel_type.check_access('read')
        if channel_type.code != 'telegram':
            raise ValidationError(_('Bot credentials can only be used for Telegram.'))
        if existing:
            existing._require_manager()
            if existing.telegram_sandbox_authorized:
                raise UserError(_('Revoke sandbox authorization before replacing credentials.'))
            if company_id != existing.company_id.id or purpose_id != existing.purpose_id.id or type_id != existing.channel_type_id.id:
                raise UserError(_('Create a new connection to change credential ownership.'))
            # Guard before verification or writing a new credential file.
            if self.env['omni.outbound.sender'].sudo().search_count([('account_id', '=', existing.id), ('is_selected', '=', True)]):
                raise UserError(_('Deactivate the runtime sender before replacing credentials.'))
        try:
            if existing and existing.credential_reference and (not token or not secret):
                saved = resolve(existing.credential_reference, existing._telegram_config())
                token = token or saved.token
                secret = secret or saved.webhook_secret
            bundle, identity = prepare_credentials(token, secret, self.env.cr.dbname, company_id)
            if existing and bundle['bot_id'] != existing.external_account_key:
                raise UserError(_('This token belongs to another bot. Create a new connection for it.'))
        except TelegramSetupError as error:
            self._raise_setup_verification_error(error)
        except UserError:
            raise
        except Exception:
            raise UserError(_('Odoo could not read the existing saved credentials. Ask your administrator to check the credential reference, encryption key and storage permissions. No credentials were changed.')) from None
        try:
            reference = runtime_secrets.store(bundle)
        except Exception:
            raise UserError(_('Telegram verified the bot, but Odoo could not save its encrypted credentials. Ask your administrator to check the Odoo data directory permissions, encryption key and available disk space. No connection changes were saved.')) from None
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: runtime_secrets.remove(reference, database))
        values.update(identity)
        values.update(credential_reference=reference, telegram_verified_at=fields.Datetime.now())
        if not existing:
            values.update(external_account_key=bundle['bot_id'], namespace=bundle['bot_id'])
        return values, reference

    def _raise_setup_verification_error(self, error):
        messages = {
            'callback_missing': _('Configure the public channel domain before verifying the webhook.'),
            'webhook_response': _('Telegram returned an invalid webhook response. Try again later.'),
            'webhook_absent': _('No webhook is registered for this bot. Register the displayed callback URL with Telegram, then verify again.'),
            'webhook_mismatch': _('This bot has a different webhook registered. Ask your administrator to review it before changing the connection.'),
            'token_format': _('The bot token format is invalid. Paste the complete token from BotFather without spaces, quotes or a URL.'),
            'secret_format': _('The webhook secret must contain 32–256 letters, numbers, underscores or hyphens. Leave it empty to generate one for a new connection.'),
            'transport': _('Couldn’t reach Telegram. Please try again. Your credentials were not changed.'),
            'rejected': _('Telegram rejected this bot token. Check that it is complete and is the current token for your bot.'),
            'rate_limit': _('Telegram temporarily limited verification requests. Wait before trying again.'),
            'unavailable': _('Telegram is temporarily unavailable. Try verification again later.'),
            'identity': _('Telegram did not return a valid matching bot identity. Verification stopped; no credentials were saved.'),
        }
        raise UserError(messages.get(error.reason, _('Bot verification failed. No credentials were saved.'))) from None

    def action_verify_telegram_bot(self):
        self.ensure_one()
        self._require_manager()
        if not self.is_telegram:
            raise UserError(_('Select a Telegram connection.'))
        config, version = self._telegram_config(), self.write_date
        try:
            secret = resolve(self.credential_reference, config)
        except Exception:
            raise UserError(_('The saved credentials could not be read. Ask your administrator to check credential storage and the encryption key. The displayed time is the last successful verification.')) from None
        try:
            _bundle, identity = prepare_credentials(secret.token, secret.webhook_secret, self.env.cr.dbname, self.company_id.id)
        except TelegramSetupError as error:
            retry = verification_retry(self, 'action_verify_telegram_bot', error)
            if retry:
                return retry
            self._raise_setup_verification_error(error)
        lock_company(self)
        self.invalidate_recordset()
        if version != self.write_date or config != self._telegram_config():
            raise UserError(_('The connection changed during verification. Try again.'))
        internal(self).write(dict(identity, telegram_verified_at=fields.Datetime.now()))
        self._audit('telegram.credentials_verified', _('Bot identity verified. No sandbox authorization, webhook registration or message delivery enabled.'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Bot verified'), 'message': _('The bot identity is valid. Delivery remains separately controlled.'), 'type': 'success',
        }}

    def action_show_telegram_webhook_secret(self):
        self.ensure_one()
        self._require_manager()
        if not self.is_telegram:
            raise UserError(_('Select a Telegram connection.'))
        wizard = self.env['omni.telegram.webhook.secret'].create({'account_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': wizard._name, 'res_id': wizard.id,
                'view_mode': 'form', 'target': 'new'}

    @api.depends("channel_type_id.code")
    def _compute_is_telegram(self):
        for record in self:
            record.is_telegram = record.channel_type_id.code == "telegram"

    telegram_sandbox_recipients = fields.Text(
        string="Sandbox recipient IDs",
        groups="omni_channel.group_omni_manager",
        copy=False,
        help="Up to ten consenting private-user numeric IDs, separated by commas or newlines. No usernames or groups.",
    )
    telegram_sandbox_evidence = fields.Text(
        string="Sandbox authorization evidence",
        groups="omni_channel.group_omni_manager",
        copy=False,
    )
    telegram_sandbox_authorized = fields.Boolean(readonly=True, copy=False)
    telegram_authorized_by = fields.Many2one("res.users", readonly=True, copy=False)
    telegram_authorized_at = fields.Datetime(readonly=True, copy=False)
    _telegram_protected = {
        "telegram_bot_name", "telegram_bot_username", "telegram_verified_at",
        "telegram_sandbox_authorized",
        "telegram_authorized_by",
        "telegram_authorized_at",
    }
    _telegram_configuration = {
        "telegram_bot_token", "telegram_webhook_secret",
        "telegram_sandbox_recipients",
        "telegram_sandbox_evidence",
        "credential_reference",
        "external_account_key",
        "namespace",
        "company_id",
        "purpose_id",
        "channel_type_id",
        "active",
    }

    @api.model
    def _discover_bot_identity(self, reference, company_id):
        if not self.env.user.has_group('omni_channel.group_omni_manager'):
            raise AccessError(_('Only an Omni administrator can configure a bot.'))
        if company_id not in self.env.companies.ids:
            raise AccessError(_('Select the connection company before configuring its bot.'))
        try:
            return discover_bot_id(reference, self.env.cr.dbname, company_id)
        except TelegramConfigurationError:
            raise UserError(_(
                'This secret reference is not provisioned for this database and company. '
                'Ask your deployment administrator for the scoped OMNI_SECRET_ reference. '
                'Do not paste the bot token here.'
            )) from None

    @api.onchange('credential_reference', 'channel_type_id', 'company_id')
    def _onchange_telegram_identity(self):
        if self.channel_type_id.code == 'telegram' and self.credential_reference and self.company_id:
            bot = self._discover_bot_identity(self.credential_reference, self.company_id.id)
            self.external_account_key = bot
            self.namespace = bot

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._telegram_protected, vals_list):
            raise AccessError(
                _("Sandbox authorization requires explicit verified confirmation."),
            )
        if any('default_' + name in self.env.context for name in ('telegram_bot_token', 'telegram_webhook_secret')):
            raise AccessError(_('Enter credentials in the connection form, not in defaults.'))
        prepared, references = [], []
        for values in vals_list:
            values, reference = self._prepare_runtime_credentials(values)
            if reference:
                references.append(reference)
            type_id = values.get('channel_type_id') or self.env.context.get('default_channel_type_id')
            if self.env['omni.channel.type'].browse(type_id).code == 'telegram':
                key = values.get('external_account_key') or self.env.context.get('default_external_account_key')
                if not key:
                    key = self._discover_bot_identity(
                        values.get('credential_reference') or self.env.context.get('default_credential_reference'),
                        values.get('company_id') or self.env.context.get('default_company_id') or self.env.company.id,
                    )
                    values['external_account_key'] = key
                if not values.get('namespace') and not self.env.context.get('default_namespace'):
                    values['namespace'] = key
            prepared.append(values)
        try:
            accounts = super().create(prepared)
            accounts.invalidate_recordset(['telegram_bot_token', 'telegram_webhook_secret'])
            for account in accounts.filtered(lambda a: a.telegram_verified_at):
                account._audit('telegram.credentials_verified', _('Runtime credentials saved after bot verification. Delivery remains disabled.'))
            return accounts
        except Exception:
            for reference in references:
                runtime_secrets.remove(reference, self.env.cr.dbname)
            raise

    def write(self, vals):
        if self._telegram_protected & vals.keys() and not is_internal(self):
            raise AccessError(_("Use the sandbox authorization actions."))
        reference = None
        if {'telegram_bot_token', 'telegram_webhook_secret'} & vals.keys():
            self.ensure_one()
            vals, reference = self._prepare_runtime_credentials(vals, existing=self)
        if not reference and {'credential_reference', 'external_account_key', 'namespace', 'company_id', 'channel_type_id'} & vals.keys():
            vals = dict(vals, telegram_verified_at=False, telegram_bot_name=False, telegram_bot_username=False)
        if self._telegram_configuration & vals.keys():
            for account in self.sorted(lambda a: (a.company_id.id, a.id)):
                account.check_access("write")
                lock_company(account)
                account.invalidate_recordset()
                if account.telegram_sandbox_authorized:
                    raise UserError(
                        _(
                            "Revoke sandbox authorization before changing the authorized configuration.",
                        ),
                    )
        try:
            result = super().write(vals)
            self.invalidate_recordset(['telegram_bot_token', 'telegram_webhook_secret'])
            if reference:
                self._audit('telegram.credentials_verified', _('Runtime credentials replaced after bot verification. Delivery remains separately controlled.'))
            return result
        except Exception:
            if reference:
                runtime_secrets.remove(reference, self.env.cr.dbname)
            raise

    @api.constrains("telegram_sandbox_recipients")
    def _validate_recipient_list(self):
        for account in self:
            if account.telegram_sandbox_recipients:
                account._telegram_recipients()

    def _telegram_recipients(self):
        self.ensure_one()
        value = self.sudo().telegram_sandbox_recipients or ""
        keys = [key for key in re.split(r"[,\s]+", value.strip()) if key]
        try:
            if not 1 <= len(keys) <= 10 or len(set(keys)) != len(keys):
                raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation
            recipients = [canonical_id(key) for key in keys]
            if self.external_account_key in recipients:
                raise ValidationError(_("Enter your personal Telegram user ID, not this bot’s ID."))
            return recipients
        except TelegramConfigurationError:
            raise ValidationError(
                _(
                    "Enter one to ten unique positive Telegram user IDs. Usernames and group IDs are not supported.",
                ),
            ) from None

    def _adapter_config(self):
        values = super()._adapter_config()
        if self.channel_type_id.code == "telegram":
            account = self.sudo()
            values.update(
                {
                    "database": self.env.cr.dbname,
                    "company_id": self.company_id.id,
                    "sandbox_authorized": bool(account.telegram_sandbox_authorized),
                    "sandbox_recipients": account._telegram_recipients()
                    if account.telegram_sandbox_recipients
                    else [],
                },
            )
        return values

    def _telegram_config(self):
        self.ensure_one()
        return {
            "account_key": self.external_account_key,
            "namespace": self.namespace,
            "sender_key": self.external_account_key,
            "credential_reference": self.credential_reference,
            "adapter": self._adapter_config(),
        }

    def action_authorize_telegram_sandbox(self):
        self.ensure_one()
        self._require_manager()
        if (
            self.channel_type_id.code != "telegram"
            or not self.active
        ):
            raise UserError(
                _(
                    "Select an active Telegram connection.",
                ),
            )
        self._telegram_recipients()
        before, version = self._telegram_config(), self.write_date
        health = get_adapter("telegram").check_sender_health(
            before,
        )  # Read-only and outside the company lock.
        lock_company(self)
        self.invalidate_recordset()
        if before != self._telegram_config() or version != self.write_date:
            raise UserError(
                _("The connection changed during verification. Review it again."),
            )
        if (
            not health.healthy
            or health.account_key != self.external_account_key
            or health.namespace != self.namespace
        ):
            raise UserError(
                _(
                    "Couldn’t verify the bot. Please try again.",
                ),
            )
        internal(self).write(
            {
                "telegram_sandbox_authorized": True,
                "telegram_authorized_by": self.env.uid,
                "telegram_authorized_at": fields.Datetime.now(),
            },
        )
        self._audit(
            "telegram.sandbox_authorized",
            _(
                "Explicit sandbox account and recipient authorization recorded after bot identity verification. No webhook registered or message sent.",
            ),
        )
        return True

    def action_revoke_telegram_sandbox(self):
        self.ensure_one()
        self._require_manager()
        if not self.is_telegram:
            raise UserError(_("Select a Telegram account."))
        lock_company(self)
        internal(self).write({"telegram_sandbox_authorized": False})
        channels = self.env["omni.channel"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("purpose_id", "=", self.purpose_id.id),
                ("channel_type_id", "=", self.channel_type_id.id),
            ],
        )
        for channel in channels:
            channel._lock()
            internal(channel).write({"dispatch_enabled": False})
            channel._advance_generation()
        self._audit(
            "telegram.sandbox_revoked",
            _(
                "Sandbox intake and new dispatch claims stopped. Previously claimed sends may still complete.",
            ),
        )
        return True


class TelegramEndpoint(models.Model):
    _inherit = "omni.inbound.endpoint"

    def _allowed(self, policy=None):
        allowed = super()._allowed(policy)
        if self.channel_type_id.code == "telegram":
            allowed = allowed and self.account_id.sudo().telegram_sandbox_authorized
        return allowed


class TelegramChannel(models.Model):
    _inherit = "omni.channel"

    is_telegram = fields.Boolean(compute="_compute_is_telegram")

    @api.depends("channel_type_id.code")
    def _compute_is_telegram(self):
        for record in self:
            record.is_telegram = record.channel_type_id.code == "telegram"

    def action_enable_telegram_dispatch(self):
        self.ensure_one()
        self._require_manager()
        sender, generation = self.selected_sender_id, self.generation
        if (
            self.channel_type_id.code != "telegram"
            or not sender
            or not sender.account_id.telegram_sandbox_authorized
        ):
            raise UserError(
                _(
                    "Authorize the Telegram sandbox account and select its verified sender first.",
                ),
            )
        if (
            not sender._check_health()
        ):  # Read-only network preflight; acquires lock only afterward.
            raise UserError(
                _("The selected bot failed verification. Dispatch remains disabled."),
            )
        self._lock()
        if self.selected_sender_id != sender or self.generation != generation:
            raise UserError(
                _("The selected sender changed. Review dispatch activation again."),
            )
        if (
            not self.active
            or not sender.account_id.telegram_sandbox_authorized
            or not self.approval_type_id.active
            or self.approval_type_id.company_id != self.company_id
        ):
            raise UserError(
                _(
                    "An active channel, authorized sandbox connection and company approval policy are required.",
                ),
            )
        endpoints = self.endpoint_ids.filtered(
            lambda e: e.account_id == sender.account_id and e._allowed(),
        )
        if not endpoints:
            raise UserError(
                _(
                    "Enable the original verified endpoint under an explicit inbound policy first.",
                ),
            )
        internal(self).write({"dispatch_enabled": True})
        self._audit(
            "telegram.dispatch_enabled",
            _(
                "New sandbox dispatch claims authorized for approved replies to the account recipient list. The scheduler remains separately controlled.",
            ),
        )
        return True


class TelegramCommand(models.Model):
    _inherit = "omni.command"

    def _telegram_guard(self):
        self.ensure_one()
        if self.channel_id.channel_type_id.code != "telegram":
            return
        sender = self.channel_id.selected_sender_id
        account = sender.account_id.sudo()
        conversation = self.conversation_id
        if (
            not sender
            or not account.telegram_sandbox_authorized
            or not conversation
            or conversation.endpoint_id.account_id != account
            or not conversation.endpoint_id._allowed()
            or self.recipient not in account._telegram_recipients()
            or conversation.thread_key != self.recipient
            or conversation.identity_id.external_key != self.recipient
        ):
            raise UserError(
                _(
                    "Telegram sandbox sends require an authorized recipient and a verified private conversation on the original bot.",
                ),
            )
        try:
            canonical_id(account.external_account_key)
            (self.body or "").encode("utf-8")
        except (TelegramConfigurationError, UnicodeError):
            raise UserError(
                _("The Telegram identity or message text is invalid."),
            ) from None
        if not self.body or not self.body.strip() or len(self.body) > 4096:
            raise UserError(_("Telegram private text must contain 1–4096 characters."))

    def action_submit(self):
        self.ensure_one()
        self.check_access("write")
        self._telegram_guard()
        return super().action_submit()

    def _check_dispatch_authorization(self):
        super()._check_dispatch_authorization()
        self._telegram_guard()


class TelegramBinding(models.AbstractModel):
    _inherit = 'omni.binding.mixin'

    @api.onchange('account_id')
    def _onchange_telegram_binding_identity(self):
        if self.account_id.channel_type_id.code == 'telegram':
            self.external_key = self.account_id.external_account_key

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            values = dict(values)
            account_id = values.get('account_id') or self.env.context.get('default_account_id')
            if account_id and not values.get('external_key') and not self.env.context.get('default_external_key'):
                account = self.env['omni.account'].browse(account_id)
                account.check_access('read')
                if account.channel_type_id.code == 'telegram':
                    values['external_key'] = account.external_account_key
            prepared.append(values)
        return super().create(prepared)


class TelegramWebhookSecret(models.TransientModel):
    _name = 'omni.telegram.webhook.secret'
    _description = 'Telegram webhook secret disclosure'

    account_id = fields.Many2one('omni.account', required=True, readonly=True)
    webhook_secret = fields.Char(compute='_compute_webhook_secret', groups='omni_channel.group_omni_manager')

    def _compute_webhook_secret(self):
        for wizard in self:
            account = wizard.account_id
            account._require_manager()
            if not account.is_telegram:
                raise AccessError(_('Select an authorized Telegram connection.'))
            try:
                wizard.webhook_secret = resolve(account.credential_reference, account._telegram_config()).webhook_secret
            except Exception:
                raise UserError(_('The webhook secret is unavailable. Check the connection credentials.')) from None


class TelegramGuidedSetup(models.Model):
    _inherit = 'omni.channel'

    setup_bot_token = fields.Char(string='Bot token', compute='_compute_setup_secret_inputs', inverse='_inverse_setup_secret_inputs', groups='omni_channel.group_omni_manager', copy=False)
    setup_webhook_secret = fields.Char(string='Webhook secret (optional)', compute='_compute_setup_secret_inputs', inverse='_inverse_setup_secret_inputs', groups='omni_channel.group_omni_manager', copy=False)
    setup_bot_name = fields.Char(related='setup_account_id.telegram_bot_name', string='Bot name')
    setup_bot_username = fields.Char(related='setup_account_id.telegram_bot_username', string='Bot username')
    setup_bot_id = fields.Char(related='setup_account_id.external_account_key', string='Bot ID')
    setup_bot_verified_at = fields.Datetime(related='setup_account_id.telegram_verified_at', string='Last verified')
    setup_bot_authorized = fields.Boolean(related='setup_account_id.telegram_sandbox_authorized')
    setup_test_recipients = fields.Text(related='setup_account_id.telegram_sandbox_recipients', readonly=False, string='Test user IDs', groups='omni_channel.group_omni_manager')
    setup_authorization_evidence = fields.Text(related='setup_account_id.telegram_sandbox_evidence', readonly=False, string='Authorization evidence', groups='omni_channel.group_omni_manager')

    def _compute_setup_secret_inputs(self):
        for channel in self:
            channel.setup_bot_token = False
            channel.setup_webhook_secret = False

    def _inverse_setup_secret_inputs(self):
        pass  # create/write consume inputs without storing them on the channel.

    @api.onchange('setup_connection_mode', 'setup_account_id')
    def _onchange_setup_credential_choice(self):
        self.setup_bot_token = False
        self.setup_webhook_secret = False

    def _save_setup_credentials(self, token, secret):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'telegram':
            raise ValidationError(_('Bot token entry is available for Telegram only.'))
        account = self.setup_account_id
        values = {'telegram_bot_token': token, 'telegram_webhook_secret': secret}
        if account or self.setup_connection_mode == 'existing':
            raise UserError(_('Saved credentials are reused for an existing connection. To connect a new bot, choose Create new connection.'))
        account = self.env['omni.account'].create(dict(values, name=self.name,
            company_id=self.company_id.id, purpose_id=self.purpose_id.id,
            channel_type_id=self.channel_type_id.id))
        self.write({'setup_account_id': account.id})
        self.invalidate_recordset(['setup_bot_token', 'setup_webhook_secret'])

    @api.model_create_multi
    def create(self, vals_list):
        if any('default_' + key in self.env.context for key in ('setup_bot_token', 'setup_webhook_secret')):
            raise AccessError(_('Enter credentials in the Credentials step, not in context defaults.'))
        if protected_input(self, {'setup_test_send_state', 'setup_webhook_fingerprint'}, vals_list) and not is_internal(self):
            raise AccessError(_('Test delivery status is managed by the test action.'))
        prepared, credentials = [], []
        for values in vals_list:
            values = dict(values)
            credentials.append((values.pop('setup_bot_token', False), values.pop('setup_webhook_secret', False)))
            prepared.append(values)
        channels = super().create(prepared)
        for channel, (token, secret) in zip(channels, credentials):
            if token or secret:
                channel._save_setup_credentials(token, secret)
        return channels

    def write(self, values):
        if {'setup_test_send_state', 'setup_webhook_fingerprint'} & values.keys() and not is_internal(self):
            raise AccessError(_('Test delivery status is managed by the test action.'))
        values = dict(values)
        token = values.pop('setup_bot_token', False)
        secret = values.pop('setup_webhook_secret', False)
        if token or secret:
            self.ensure_one()
            self._require_manager()
        result = super().write(values)
        if token or secret:
            self._save_setup_credentials(token, secret)
        return result

    setup_test_recipient = fields.Char(compute='_compute_setup_test_recipient', string='Tester', groups='omni_channel.group_omni_manager')
    setup_test_text = fields.Char(compute='_compute_setup_test_recipient', string='Message', groups='omni_channel.group_omni_manager')
    setup_webhook_fingerprint = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    setup_test_send_state = fields.Selection([
        ('pending', 'Sending'), ('sent', 'Test message sent'),
        ('failed', 'Not sent'), ('unknown', 'Delivery unconfirmed'),
    ], readonly=True, copy=False, groups='omni_channel.group_omni_manager')

    @api.depends('setup_test_recipients')
    def _compute_setup_test_recipient(self):
        for channel in self:
            recipients = channel.setup_account_id._telegram_recipients() if channel.setup_test_recipients else []
            channel.setup_test_recipient = recipients[0] if recipients else False
            channel.setup_test_text = TEST_MESSAGE

    def _claim_setup_test(self):
        self.ensure_one()
        self._require_manager()
        self._lock()
        self._check_setup_account()
        account = self.setup_account_id
        if not self.is_telegram or not self.active or not account.telegram_verified_at or not self._is_setup_connection_ready():
            raise UserError(_('Connect Telegram first.'))
        if self.setup_test_send_state in ('pending', 'sent', 'unknown'):
            raise UserError(_('A test was already sent or may still be delivered. Check Telegram.'))
        recipient = account._telegram_recipients()[0]
        if self.env['omni.blocked.identity']._matches(self, account.namespace, recipient):
            raise UserError(_('This tester is blocked.'))
        try:
            secret = resolve(account.credential_reference, account._telegram_config())
        except Exception:
            raise UserError(_('The saved bot credentials could not be read.')) from None
        if not account.telegram_sandbox_authorized:
            account.action_authorize_telegram_sandbox()
        if not self._is_setup_receiving_ready():
            self.action_setup_enable_receiving()
        internal(self).write({'setup_test_send_state': 'pending'})
        self._audit('telegram.setup_test_authorized', json.dumps({
            'account': account.id, 'tester': recipient, 'message': TEST_MESSAGE,
            'policy': 'manager-confirmed-fixed-setup-test',
        }))
        return secret.token, recipient

    def _finish_setup_test(self, state, detail):
        self._require_manager()
        self._lock()
        if self.setup_test_send_state != 'pending' or state not in ('sent', 'failed', 'unknown'):
            raise UserError(_('The test result cannot be changed.'))
        internal(self).write({'setup_test_send_state': state})
        self._audit('telegram.setup_test_result', json.dumps({'state': state, 'detail': detail}))

    def action_setup_send_test(self):
        self.ensure_one()
        self._require_manager()
        # Commit the claim before I/O so repeated clicks, HTTP retries and process
        # failure cannot silently send the same diagnostic twice.
        context = {'allowed_company_ids': self.env.companies.ids}
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            token, recipient = record._claim_setup_test()
            cr.commit()
        state, detail = send_test_message(token, recipient)
        with self.env.registry.cursor() as cr:
            record = api.Environment(cr, self.env.uid, context)[self._name].browse(self.id)
            record._finish_setup_test(state, detail)
            cr.commit()
        self.invalidate_recordset(['setup_test_send_state'])
        messages = {
            'sent': _('Test message sent.'),
            'failed': (_('Open the bot and press Start, then try again.') if detail == 'start_bot' else _('Test not sent. Please try again.')),
            'unknown': _('Delivery unconfirmed. Check Telegram before sending another test.'),
        }
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': messages[state], 'type': 'success' if state == 'sent' else 'warning',
            'sticky': state != 'sent',
        }}

    def _setup_connection_fingerprint(self):
        account = self.setup_account_id
        values = [self.setup_callback_url, account.id, account.external_account_key,
                  account.namespace, account.credential_reference, str(account.telegram_verified_at)]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def _is_setup_connection_ready(self):
        if not self.is_telegram:
            return super()._is_setup_connection_ready()
        account = self.setup_account_id
        return bool(self.active and account.active and account.telegram_verified_at and
                    (self.setup_webhook_fingerprint == self._setup_connection_fingerprint()
                     if self.setup_webhook_fingerprint else self._is_setup_receiving_ready()))

    def _registration_fingerprint(self):
        values = [self.setup_callback_url, self.setup_account_id.id,
                  self.setup_account_id._telegram_config()]
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def action_setup_connect_telegram(self):
        return self._connect_telegram()

    def _connect_telegram(self, expected_remote=None, expected_config=None):
        self.ensure_one()
        self._require_manager()
        self._lock()
        self._check_setup_account()
        account = self.setup_account_id
        endpoint = self.setup_endpoint_id
        if not self.is_telegram or not account or not endpoint or not account.telegram_verified_at:
            raise UserError(_('Verify the bot in Credentials first.'))
        account._require_manager()
        if not self.active or not endpoint.active or not account.active:
            raise UserError(_('Restore the channel and connection before connecting Telegram.'))
        lock_company(account)
        from odoo.addons.omni_channel.models.deployment import valid_callback_url
        url = self.setup_callback_url
        if not valid_callback_url(url, endpoint.route_key):
            raise UserError(_('Enter your public HTTPS webhook URL first.'))
        fingerprint = self._registration_fingerprint()
        if expected_config and expected_config != fingerprint:
            raise UserError(_('The connection changed. Close this dialog and click Connect Telegram again.'))
        try:
            secret = resolve(account.credential_reference, account._telegram_config())
        except Exception:
            raise UserError(_('The saved credentials could not be read. Check credential storage.')) from None
        try:
            current = webhook_info(secret.token)['url']
        except TelegramSetupError as error:
            account._raise_setup_verification_error(error)
        remote_digest = hashlib.sha256(current.encode()).hexdigest()
        if expected_remote and expected_remote != remote_digest:
            raise UserError(_('Telegram’s webhook changed. Close this dialog and click Connect Telegram again.'))
        if current and current != url and not expected_remote:
            wizard = self.env['omni.telegram.webhook.registration'].create({
                'channel_id': self.id, 'callback_url': url,
                'remote_digest': remote_digest, 'config_digest': fingerprint,
            })
            return {'type': 'ir.actions.act_window', 'res_model': wizard._name,
                    'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
        # Permission/config checks and serialization occur before any external mutation.
        try:
            previous_error = register_webhook(secret.token, secret.webhook_secret, url)
        except TelegramSetupError as error:
            messages = {
                'registration_rejected': _('Telegram rejected the registration. Check that the public HTTPS URL and certificate are reachable, then try Connect Telegram again.'),
                'registration_unknown': _('Telegram did not confirm the request. The webhook may have changed. Click Verify webhook before trying Connect Telegram again.'),
                'registration_unconfirmed': _('Telegram accepted the registration, but its final settings could not be confirmed. Click Verify webhook to check them.'),
            }
            if error.reason not in messages:
                account._raise_setup_verification_error(error)
            self._audit('telegram.webhook_registration', error.reason)
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _('Webhook registration needs attention'), 'message': messages[error.reason],
                'type': 'warning', 'sticky': True,
            }}
        internal(self).write({'setup_webhook_fingerprint': self._setup_connection_fingerprint()})
        self._audit('telegram.webhook_registered', _('Webhook registered. Test-user receiving remains disabled until the final test confirmation.'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Telegram connected'),
            'message': (_('Connected. Telegram reports a previous delivery error; send a new test message.')
                        if previous_error else _('Connected. Continue to Branding.')),
            'type': 'warning' if previous_error else 'success', 'sticky': True,
        }}

    def action_setup_complete_step(self, step):
        if step != 4 or not self.is_telegram:
            return super().action_setup_complete_step(step)
        self.ensure_one()
        self._require_manager()
        self._lock()
        if self.setup_test_send_state != 'sent':
            raise UserError(_('Send the test message first.'))
        with self.env.cr.savepoint():
            completed = super().action_setup_complete_step(step)
            if self.selected_sender_id != self.setup_sender_id:
                self.setup_sender_id.action_activate(self.generation)
            if self.selected_sender_id != self.setup_sender_id:
                raise UserError(_('The bot could not be checked. Try Finish setup again.'))
        return completed

    def action_setup_verify_webhook(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'telegram':
            return super().action_setup_verify_webhook()
        self._check_setup_account()
        account = self.setup_account_id
        url = self.setup_callback_url
        if not account or not self.setup_endpoint_id:
            raise UserError(_('Complete Credentials first.'))
        if not url:
            raise UserError(_('Configure the public channel domain before verifying the webhook.'))
        config = account._telegram_config()
        try:
            secret = resolve(account.credential_reference, config)
        except Exception:
            raise UserError(_('The saved credentials could not be read. Ask your administrator to check credential storage.')) from None
        try:
            has_delivery_error = verify_webhook(secret.token, url)
        except TelegramSetupError as error:
            retry = verification_retry(self, 'action_setup_verify_webhook', error)
            if retry:
                return retry
            account._raise_setup_verification_error(error)
        self.invalidate_recordset()
        account.invalidate_recordset()
        if self.setup_account_id != account or self.setup_callback_url != url or account._telegram_config() != config:
            raise UserError(_('The connection changed during verification. Try again.'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Webhook registered'),
            'message': (_('The URL matches, but Telegram reports a previous delivery error. Send a new test message to check delivery.')
                        if has_delivery_error else _('Telegram has this callback URL registered. Send a test message to confirm delivery.')),
            'type': 'warning' if has_delivery_error else 'success',
            'sticky': True,
        }}

    def action_setup_verify_bot(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_account_id:
            raise UserError(_('Enter a bot token or select an existing connection.'))
        return self.setup_account_id.action_verify_telegram_bot()

    def action_setup_prepare_connection(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != 'telegram':
            return super().action_setup_prepare_connection()
        self._lock()
        self._check_setup_account()
        account = self.setup_account_id
        if not account or not account.telegram_verified_at:
            raise UserError(_('Verify the bot in Credentials before continuing.'))
        for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
            existing = self.env[model].sudo().with_context(active_test=False).search([
                ('account_id', '=', account.id), ('channel_id', '!=', self.id),
            ], limit=1)
            if existing:
                raise UserError(_('This bot already belongs to another channel. Select a different bot.'))
            binding = self.env[model].with_context(active_test=False).search([('account_id', '=', account.id), ('channel_id', '=', self.id)], limit=1)
            if binding and not binding.active:
                raise UserError(_('Restore this connection’s archived sender or endpoint before continuing.'))
            if not binding:
                self.env[model].create({'name': self.name, 'channel_id': self.id, 'account_id': account.id})
        if not self.env['omni.inbound.policy'].search_count([('channel_id', '=', self.id)]):
            self.env['omni.inbound.policy'].create({'name': self.name, 'channel_id': self.id})
        self.invalidate_recordset(['setup_policy_id', 'setup_sender_id', 'setup_endpoint_id', 'setup_callback_url'])
        return True

    @api.depends('setup_endpoint_state', 'setup_endpoint_health', 'setup_callback_url', 'setup_bot_authorized', 'setup_webhook_fingerprint', 'setup_account_id.active', 'setup_account_id.telegram_verified_at', 'setup_account_id.credential_reference', 'setup_account_id.external_account_key', 'setup_account_id.namespace', 'active')
    def _compute_setup_receiving_ready(self):
        super()._compute_setup_receiving_ready()

    def _is_setup_receiving_ready(self):
        return super()._is_setup_receiving_ready() and (not self.is_telegram or self.setup_bot_authorized)

    def action_setup_validate_step(self, step):
        result = super().action_setup_validate_step(step)
        return result

    def action_setup_enable_receiving(self):
        self.ensure_one()
        self._require_manager()
        if self.is_telegram and not self.setup_bot_authorized:
            raise UserError(_('Authorize the consenting sandbox users before enabling receiving.'))
        return super().action_setup_enable_receiving()

    def action_setup_open_bot(self):
        self.ensure_one()
        self._require_manager()
        username = self.setup_bot_username or ''
        if not self.is_telegram or self.setup_endpoint_state != 'enabled' or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
            raise UserError(_('Enable receiving for a verified Telegram bot first.'))
        return {'type': 'ir.actions.act_url', 'url': 'https://t.me/' + username, 'target': 'new'}

    def action_setup_authorize_bot(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_account_id:
            raise UserError(_('Complete Credentials first.'))
        return self.setup_account_id.action_authorize_telegram_sandbox()

    def action_setup_webhook_secret(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_account_id:
            raise UserError(_('Complete Credentials first.'))
        return self.setup_account_id.action_show_telegram_webhook_secret()

    def action_setup_activate(self):
        self.ensure_one()
        self._require_manager()
        if not self.setup_sender_id or not self.setup_endpoint_id or self.setup_endpoint_id.state != 'enabled':
            raise UserError(_('Verify the bot and enable receiving in Connect & verify first.'))
        if self.selected_sender_id != self.setup_sender_id:
            self.setup_sender_id.action_activate(self.generation)
        if self.selected_sender_id != self.setup_sender_id:
            raise UserError(_('Sender verification failed. Activation remains disabled.'))
        return self.action_enable_telegram_dispatch()


class TelegramWebhookRegistration(models.TransientModel):
    _name = 'omni.telegram.webhook.registration'
    _description = 'Confirm Telegram webhook replacement'

    channel_id = fields.Many2one('omni.channel', required=True, readonly=True)
    callback_url = fields.Char(required=True, readonly=True)
    remote_digest = fields.Char(required=True, readonly=True)
    config_digest = fields.Char(required=True, readonly=True)

    def action_confirm(self):
        self.ensure_one()
        self.check_access('read')
        self.channel_id._require_manager()
        result = self.channel_id._connect_telegram(self.remote_digest, self.config_digest)
        if result.get('tag') == 'display_notification':
            result['params']['next'] = {'type': 'ir.actions.act_window_close'}
        return result
