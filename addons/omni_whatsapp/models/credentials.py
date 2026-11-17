"""WhatsApp-only draft credentials; no webhook activation or message sending."""
import os

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input

from ..providers.connection import ConnectionRejected, GraphReadOnly, select_phone, verify_account
from ..providers import business, vault

PROFILE_FIELDS = {"whatsapp_business_id", "whatsapp_phone_name", "whatsapp_phone_number", "whatsapp_verified_at"}


def client():
    version = os.environ.get("OMNI_WHATSAPP_GRAPH_VERSION")
    if not version:
        raise UserError(_("Ask your administrator to configure the WhatsApp API version."))
    try:
        return GraphReadOnly(version)
    except ConnectionRejected:
        raise UserError(_("The configured WhatsApp API version is invalid.")) from None


def numbers(account_id, token):
    try:
        return verify_account(client(), account_id, token)
    except ConnectionRejected as error:
        messages = {
            "credentials": _("Check the access token and account permissions."),
            "account": _("Enter a valid business account ID."),
            "no_numbers": _("No phone numbers are available for this account."),
            "rate_limited": _("Meta is busy. Please try again later."),
            "network": _("Could not reach Meta. Please try again."),
        }
        raise UserError(messages.get(str(error), _("Could not verify this WhatsApp account."))) from None


class WhatsAppAccount(models.Model):
    _inherit = "omni.account"

    whatsapp_business_id = fields.Char(readonly=True, copy=False)
    whatsapp_phone_name = fields.Char(readonly=True, copy=False)
    whatsapp_phone_number = fields.Char(readonly=True, copy=False)
    whatsapp_verified_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, PROFILE_FIELDS, vals_list) and not is_internal(self):
            raise AccessError(_("WhatsApp details are recorded by account verification."))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, PROFILE_FIELDS, [values]) and not is_internal(self):
            raise AccessError(_("WhatsApp details are recorded by account verification."))
        return super().write(values)

    def _whatsapp_credentials(self):
        self.ensure_one()
        self._require_manager()
        if self.channel_type_id.code != "whatsapp" or not self.active or not self.whatsapp_verified_at:
            raise UserError(_("Verify this WhatsApp account first."))
        try:
            return vault.load(self.credential_reference, database=self.env.cr.dbname,
                              company_id=self.company_id.id, purpose_id=self.purpose_id.id,
                              phone_number_id=self.external_account_key,
                              business_account_id=self.whatsapp_business_id)
        except Exception:
            raise UserError(_("The saved WhatsApp credentials could not be read.")) from None


    # ------------------------------------------------------------------ templates (for Messaging Marketing)

    def _whatsapp_business(self):
        """``(version, business account, token)`` for server-side template work.

        The caller has checked the person's own access to the template and calls with ``sudo()``: marketers
        submit templates without being Omnichannel administrators, and never see the token.
        """
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_("Only the template actions can use this account."))
        if self.channel_type_id.code != "whatsapp" or not self.active or not self.whatsapp_verified_at:
            raise UserError(_("Verify this WhatsApp account first."))
        version = os.environ.get("OMNI_WHATSAPP_GRAPH_VERSION")
        if not version:
            raise UserError(_("Ask your administrator to configure the WhatsApp API version."))
        try:
            credentials = vault.load(self.credential_reference, database=self.env.cr.dbname,
                                     company_id=self.company_id.id, purpose_id=self.purpose_id.id,
                                     phone_number_id=self.external_account_key,
                                     business_account_id=self.whatsapp_business_id)
        except Exception:
            raise UserError(_("The saved WhatsApp credentials could not be read.")) from None
        return version, self.whatsapp_business_id, credentials["access_token"]

    def _whatsapp_template_texts(self):
        return {
            "credentials": _("Meta refused the access token. An Omnichannel administrator checks that it may "
                             "manage templates (whatsapp_business_management)."),
            "rate_limited": _("Meta is busy. Please try again later."),
            "configuration": _("The template's name or language is not one Meta accepts."),
            "body": _("The message is empty or longer than 1,024 characters."),
            "fields": _("The fields of the message could not be numbered for Meta."),
            "example": _("Give a one-line example for each field."),
            "header": _("The header is one line of at most 60 characters."),
            "footer": _("The footer is one line of at most 60 characters."),
            "button": _("The button needs a text of at most 25 characters and an https:// link."),
        }

    def _whatsapp_template_submit(self, *, name, language, body, example, header="", footer="",
                                  button_label="", button_url=""):
        """Create a marketing template at Meta: ``{'id', 'status'}`` (status as in ``business.STATUSES``).

        When Meta's answer is lost, the template may or may not exist there: the id is empty and the status is
        "review"; the next read of the templates settles it.
        """
        version, business_account, token = self._whatsapp_business()
        texts = self._whatsapp_template_texts()
        try:
            components = business.template_components(
                body=body, example=example, header=header, footer=footer, button_label=button_label,
                button_url=button_url)
            return business.submit_template(version, business_account, token, name=name, language=language,
                                            components=components)
        except business.BusinessRejected as error:
            code = str(error)
            if code == "unknown":
                return {"id": "", "status": "review"}
            if code == "refused":
                raise UserError(_("Meta did not accept the template: %s",
                                  error.detail or _("no reason given"))) from None
            raise UserError(texts.get(code, _("Meta could not be reached. Please try again."))) from None

    def _whatsapp_template_list(self):
        version, business_account, token = self._whatsapp_business()
        try:
            return business.list_templates(version, business_account, token)
        except business.BusinessRejected as error:
            raise UserError(self._whatsapp_template_texts().get(
                str(error), _("Could not reach Meta. Please try again."))) from None


class WhatsAppChannel(models.Model):
    _inherit = "omni.channel"

    is_whatsapp = fields.Boolean(compute="_compute_is_whatsapp")
    whatsapp_credentials_ui = fields.Json(compute="_compute_whatsapp_credentials_ui", groups="omni_channel.group_omni_manager")

    @api.depends("channel_type_id.code")
    def _compute_is_whatsapp(self):
        for channel in self:
            channel.is_whatsapp = channel.channel_type_id.code == "whatsapp"

    @api.depends("setup_account_id", "setup_account_id.whatsapp_verified_at")
    def _compute_whatsapp_credentials_ui(self):
        for channel in self:
            account = channel.setup_account_id
            channel.whatsapp_credentials_ui = ({"account": account.whatsapp_business_id,
                "phone": account.external_account_key, "name": account.whatsapp_phone_name,
                "number": account.whatsapp_phone_number} if channel.is_whatsapp and account.whatsapp_verified_at else {})

    def _require_whatsapp_setup(self):
        self.ensure_one()
        self._require_manager()
        self._check_scope()
        if not self.active or not self.is_whatsapp:
            raise UserError(_("Choose an active WhatsApp channel."))

    def action_whatsapp_verify_account(self, business_account_id, access_token):
        self._require_whatsapp_setup()
        if self.setup_account_id:
            raise UserError(_("This channel already has a saved connection."))
        return [{"id": phone.id, "name": phone.name, "number": phone.number}
                for phone in numbers(business_account_id, access_token)]

    def action_whatsapp_save_connection(self, business_account_id, access_token, phone_number_id):
        self._require_whatsapp_setup()
        expected_scope = (self.company_id.id, self.purpose_id.id, self.channel_type_id.id)
        try:
            phone = select_phone(numbers(business_account_id, access_token), phone_number_id)
        except ConnectionRejected:
            raise UserError(_("Choose a phone number from this account.")) from None
        self._lock()
        self.invalidate_recordset(["setup_account_id", "sender_ids", "endpoint_ids", "company_id", "purpose_id", "channel_type_id", "active", "is_whatsapp"])
        self._require_whatsapp_setup()
        if expected_scope != (self.company_id.id, self.purpose_id.id, self.channel_type_id.id):
            raise UserError(_("The channel changed. Reopen setup and verify again."))
        if self.setup_account_id or self.sender_ids or self.endpoint_ids:
            raise UserError(_("This channel already has a saved connection."))
        bundle = {"database": self.env.cr.dbname, "company_id": self.company_id.id,
                  "purpose_id": self.purpose_id.id, "business_account_id": business_account_id,
                  "phone_number_id": phone.id, "access_token": access_token}
        reference = vault.store(bundle)
        database = self.env.cr.dbname
        self.env.cr.postrollback.add(lambda: vault.remove(reference, database))
        try:
            with self.env.cr.savepoint():
                account = internal(self.env["omni.account"]).create({
                    "name": phone.name, "company_id": self.company_id.id, "purpose_id": self.purpose_id.id,
                    "channel_type_id": self.channel_type_id.id, "external_account_key": phone.id,
                    "namespace": phone.id, "credential_reference": reference,
                    "whatsapp_business_id": business_account_id, "whatsapp_phone_name": phone.name,
                    "whatsapp_phone_number": phone.number, "whatsapp_verified_at": fields.Datetime.now(),
                })
                self.write({"setup_account_id": account.id})
                self._audit("whatsapp.credentials_verified", str(account.id))
        except Exception:
            vault.remove(reference, database)
            raise
        return True

    def action_setup_prepare_connection(self):
        self.ensure_one()
        if not self.is_whatsapp:
            return super().action_setup_prepare_connection()
        self._require_whatsapp_setup()
        self._check_setup_account()
        if not self.setup_account_id:
            raise UserError(_("Verify the account and choose a phone number first."))
        self.setup_account_id._whatsapp_credentials()
        return True
