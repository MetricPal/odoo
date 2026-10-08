import re

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
)


class TelegramAccount(models.Model):
    _inherit = "omni.account"

    is_telegram = fields.Boolean(compute="_compute_is_telegram")

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
        "telegram_sandbox_authorized",
        "telegram_authorized_by",
        "telegram_authorized_at",
    }
    _telegram_configuration = {
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
        prepared = []
        for values in vals_list:
            values = dict(values)
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
        return super().create(prepared)

    def write(self, vals):
        if self._telegram_protected & vals.keys() and not is_internal(self):
            raise AccessError(_("Use the sandbox authorization actions."))
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
        return super().write(vals)

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
            return [canonical_id(key) for key in keys]
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
            or not (self.telegram_sandbox_evidence or "").strip()
        ):
            raise UserError(
                _(
                    "Select an active Telegram connection and record explicit sandbox authorization evidence.",
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
                    "Bot verification failed. Check the scoped secret bundle and deployment sandbox network switch.",
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
