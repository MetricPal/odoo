from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        session_info = super().session_info()
        if session_info.get("uid"):
            session_info["user_email"] = self.env.user.email or ""
        return session_info
