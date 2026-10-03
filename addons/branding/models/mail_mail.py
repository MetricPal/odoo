from odoo import models
from odoo.tools import file_open
from odoo.tools.mimetypes import guess_mimetype

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_PATH, INLINE_LOGO_SRC


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _branding_company(self):
        self.ensure_one()
        return (self.record_company_id or self.env.company).sudo()

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        outgoing_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        company = self._branding_company()
        for outgoing_values in outgoing_list:
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
