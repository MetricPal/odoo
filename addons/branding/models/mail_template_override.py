from odoo import api, fields, models


class BrandingMailTemplateOverride(models.Model):
    _name = 'branding.mail.template.override'
    _description = 'Branding Mail Template Override'

    xmlid = fields.Char(required=True)
    template_name = fields.Char(required=True)
    email_layout_xmlid = fields.Char(default='branding.branding_mail_layout', required=True)
    body_html = fields.Text(required=True)

    @api.model
    def apply_all(self):
        for override in self.sudo().search([]):
            template = self.env.ref(override.xmlid, raise_if_not_found=False)
            if not template:
                continue
            template.sudo().write({
                'name': override.template_name,
                'email_layout_xmlid': override.email_layout_xmlid,
                'email_layout_force_header': False,
                'email_layout_force_footer': False,
                'body_html': override.body_html,
            })
