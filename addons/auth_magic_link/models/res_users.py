from odoo import _, api, models
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def authenticate(self, credential, user_agent_env):
        auth_type = credential.get("type")

        if auth_type == "magic_link":
            link = self.env["auth.magic.link"].find_valid_token(
                credential.get("token")
            )
            if not link:
                raise AccessDenied(_("Invalid or expired sign-in link."))

            # The session authentication pipeline requires a login before it
            # delegates token validation to _check_credentials.
            credential["login"] = link.user_id.login

        if auth_type == "password":
            # Only block interactive web authentication. API/key based
            # authentication is not changed by this module.
            method = self.env["auth.magic.link"].effective_login_method()
            if method not in {"password", "both"} and (user_agent_env or {}).get(
                "interactive", True
            ):
                raise AccessDenied(
                    _("Username and password login is disabled by the system administrator.")
                )

        return super().authenticate(credential, user_agent_env)

    def _check_credentials(self, credential, user_agent_env):
        try:
            return super()._check_credentials(credential, user_agent_env)
        except AccessDenied:
            if credential.get("type") != "magic_link":
                raise
            if self.env["auth.magic.link"].effective_login_method() not in {
                "magic_link",
                "both",
            }:
                raise

            link = self.env["auth.magic.link"].sudo().consume_token(
                credential.get("token")
            )
            if not link or link.user_id != self.env.user:
                raise

            return {
                "uid": self.env.user.id,
                "auth_method": "magic_link",
                "mfa": "default",
            }
