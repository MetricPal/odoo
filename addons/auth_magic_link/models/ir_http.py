from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        if info.get("uid"):
            # Kept only in this user's own browser for the "Choose a user" list.
            info["user_email"] = self.env.user.email or ""
        return info
