from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    auth_login_method = fields.Selection(
        [
            ("password", "Password"),
            ("magic_link", "Email verification link"),
            ("both", "Both"),
            ("oauth_only", "OAuth only"),
        ],
        string="Login method",
        default="password",
        config_parameter="auth_magic_link.login_method",
        required=True,
    )
    auth_magic_link_ttl = fields.Integer(
        string="Verification link validity (minutes)",
        default=10,
        config_parameter="auth_magic_link.expiry_minutes",
    )
    auth_magic_link_expiry_minutes = fields.Integer(
        string="Magic Link validity",
        default=10,
        config_parameter="auth_magic_link.expiry_minutes",
    )
    auth_admin_has_valid_email = fields.Boolean(compute="_compute_auth_requirements")
    auth_outbound_email_ready = fields.Boolean(compute="_compute_auth_requirements")
    auth_admin_has_active_oauth = fields.Boolean(compute="_compute_auth_requirements")

    @api.model
    def _system_admin(self):
        return self.env.ref("base.user_admin", raise_if_not_found=False)

    @api.model
    def _admin_has_valid_email(self):
        admin = self._system_admin()
        admin = admin.sudo() if admin else admin
        return bool(admin and admin.active and admin.email and email_normalize(admin.email))

    @api.model
    def _admin_has_active_oauth(self):
        admin = self._system_admin()
        admin = admin.sudo() if admin else admin
        return bool(
            admin
            and admin.active
            and admin.oauth_provider_id
            and admin.oauth_provider_id.enabled
            and admin.oauth_uid
        )

    @api.model
    def _outbound_email_ready(self):
        return bool(
            self.env["ir.mail_server"].sudo().search_count(
                [("active", "=", True)], limit=1
            )
        )

    @api.depends_context("uid")
    def _compute_auth_requirements(self):
        email_ok = self._admin_has_valid_email()
        outbound_email_ok = self._outbound_email_ready()
        oauth_ok = self._admin_has_active_oauth()
        for rec in self:
            rec.auth_admin_has_valid_email = email_ok
            rec.auth_outbound_email_ready = outbound_email_ok
            rec.auth_admin_has_active_oauth = oauth_ok

    @api.constrains("auth_magic_link_ttl")
    def _check_auth_magic_link_ttl(self):
        for rec in self:
            if not 1 <= rec.auth_magic_link_ttl <= 60:
                raise ValidationError(
                    _("Verification link validity must be between 1 and 60 minutes.")
                )

    def set_values(self):
        self.ensure_one()
        if self.auth_login_method in ("magic_link", "both"):
            blockers = []
            if not self._admin_has_valid_email():
                blockers.append(_("a valid email address on the System Administrator"))
            if not self._outbound_email_ready():
                blockers.append(_("an active outgoing mail server"))
            if blockers:
                raise ValidationError(
                    _("Email verification login requires %s.")
                    % _(" and ").join(blockers)
                )
        if self.auth_login_method == "oauth_only" and not self._admin_has_active_oauth():
            raise ValidationError(
                _("OAuth only requires the System Administrator to be linked to an enabled OAuth provider.")
            )
        return super().set_values()
