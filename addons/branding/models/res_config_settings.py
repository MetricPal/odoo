from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    email_body_background_color = fields.Char(
        related='company_id.email_body_background_color',
        readonly=False,
    )
    email_content_background_color = fields.Char(
        related='company_id.email_content_background_color',
        readonly=False,
    )
    email_footer_background_color = fields.Char(
        related='company_id.email_footer_background_color',
        readonly=False,
    )
