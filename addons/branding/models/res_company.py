from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    email_body_background_color = fields.Char(
        "Email Body Background",
        default="#F7F8FA",
        readonly=False,
    )
    email_content_background_color = fields.Char(
        "Email Content Background",
        default="#FFFFFF",
        readonly=False,
    )
    email_footer_background_color = fields.Char(
        "Email Footer Background",
        default="#EEEEEE",
        readonly=False,
    )
