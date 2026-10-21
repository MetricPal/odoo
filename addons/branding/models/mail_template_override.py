import hashlib

from odoo import api, fields, models


class BrandingMailTemplateOverride(models.Model):
    """Branded body and layout for a mail template identified by XML ID.

    Overrides are plain data, so branding needs no dependency on the apps that
    own the templates. They are applied when they are loaded (branding install
    or upgrade) and whenever an app is installed later and loads one of the
    targeted templates (see ``mail.template._load_records`` below).
    """
    _name = 'branding.mail.template.override'
    _description = 'Branding Mail Template Override'

    xmlid = fields.Char(required=True, index=True)
    template_name = fields.Char(required=True)
    email_layout_xmlid = fields.Char(default='branding.branding_mail_layout', required=True)
    body_html = fields.Text(required=True)
    applied_checksum = fields.Char(readonly=True, copy=False)

    def _checksum(self):
        self.ensure_one()
        return hashlib.sha256('\x00'.join(
            [self.template_name or '', self.email_layout_xmlid or '', self.body_html or ''],
        ).encode()).hexdigest()

    def _apply(self, force=False):
        """Write each override onto its template when it exists.

        Skips overrides already applied with the same content, so reloading
        unchanged data never overwrites later manual edits of the template.
        """
        applied = self.browse()
        for override in self.sudo():
            template = self.env.ref(override.xmlid, raise_if_not_found=False)
            if not template or template._name != 'mail.template':
                continue
            # Branding does not depend on the apps that own the templates, so it
            # can load before them during an upgrade: the template row exists
            # but its model is not in the registry yet. Leave it pending; it is
            # applied when the app loads it or when the registry is ready.
            if template.sudo().model not in self.env.registry:
                continue
            checksum = override._checksum()
            if not force and override.applied_checksum == checksum:
                continue
            template.sudo().write({
                'name': override.template_name,
                'email_layout_xmlid': override.email_layout_xmlid,
                'email_layout_force_header': False,
                'email_layout_force_footer': False,
                'body_html': override.body_html,
            })
            override.applied_checksum = checksum
            applied |= override
        return applied

    @api.model
    def apply_all(self):
        """Apply every override; kept for manual use from a shell or action."""
        return self.sudo().search([])._apply(force=True)

    def _load_records(self, data_list, update=False):
        records = super()._load_records(data_list, update=update)
        records._apply()
        return records

    def _register_hook(self):
        """Apply overrides left pending while their app was not loaded yet."""
        super()._register_hook()
        if not self.env.cr.readonly:
            self.sudo().search([])._apply()


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    def _load_records(self, data_list, update=False):
        records = super()._load_records(data_list, update=update)
        xmlids = [data['xml_id'] for data in data_list if data.get('xml_id')]
        if xmlids:
            overrides = self.env['branding.mail.template.override'].sudo().search([('xmlid', 'in', xmlids)])
            # The template was (re)loaded from its module: re-apply branding.
            overrides._apply(force=True)
        return records
