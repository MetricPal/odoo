from odoo import models, tools
from odoo.tools import file_open
from odoo.tools.mimetypes import guess_mimetype

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_PATH, INLINE_LOGO_SRC


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _branding_company(self):
        self.ensure_one()
        return (self.record_company_id or self.env.company).sudo()

    def _branding_context_record(self):
        self.ensure_one()
        if not self.model or not self.res_id or self.model not in self.env:
            return None
        return self.env[self.model].sudo().browse(self.res_id).exists()

    def _branding_should_wrap_body(self, body):
        self.ensure_one()
        if not body:
            return False
        if 'mailing_id' in self._fields and self.mailing_id:
            return False
        return not any(
            marker in body
            for marker in (
                'data-branding-body-canvas="1"',
                'data-branding-content-shell="1"',
                'data-branding-mail-footer="1"',
                'data-branding-email-kind="digest"',
            )
        )

    def _branding_wrap_body(self, body):
        self.ensure_one()
        return self.env['mail.render.mixin']._render_encapsulate(
            'branding.branding_mail_layout',
            body,
            add_context={'company': self._branding_company()},
            context_record=self._branding_context_record(),
        )

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        outgoing_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        company = self._branding_company()
        for outgoing_values in outgoing_list:
            body = outgoing_values.get('body') or ''
            if self._branding_should_wrap_body(body):
                body = self._branding_wrap_body(body)
                outgoing_values['body'] = body
                outgoing_values['body_alternative'] = tools.html2plaintext(body)
            if INLINE_LOGO_SRC not in (outgoing_values.get('body') or ''):
                continue
            logo_content = company.logo_web.content if company.logo_web else None
            if logo_content is None:
                with file_open(INLINE_LOGO_PATH, mode='rb') as logo_file:
                    logo_content = logo_file.read()
            logo_attachment = (
                INLINE_LOGO_FILENAME,
                logo_content,
                guess_mimetype(logo_content, default='image/png'),
            )
            attachments = outgoing_values.get('attachments', [])
            if not any(attachment[0] == INLINE_LOGO_FILENAME for attachment in attachments):
                outgoing_values['attachments'] = [*attachments, logo_attachment]
        return outgoing_list
