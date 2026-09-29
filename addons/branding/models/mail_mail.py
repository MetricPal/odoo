import base64
import re

from odoo import models
from odoo.tools import file_open
from odoo.tools.mimetypes import guess_mimetype

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_PATH, INLINE_LOGO_SRC


_COMPANY_LOGO_SRC_RE = re.compile(
    r'(?P<prefix>\bsrc=(?P<quote>["\']))'
    r'(?P<url>(?:https?://[^"\']+)?/(?:logo(?:\.png)?|web/binary/company_logo)'
    r'\?[^"\']*\bcompany=(?P<company_id>\d+)[^"\']*)'
    r'(?P=quote)',
    flags=re.IGNORECASE,
)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        outgoing_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        logo_cache = {}
        for outgoing_values in outgoing_list:
            body = outgoing_values.get('body') or ''
            company_logo_match = _COMPANY_LOGO_SRC_RE.search(body)
            if company_logo_match:
                body = _COMPANY_LOGO_SRC_RE.sub(
                    lambda match: f"{match.group('prefix')}{INLINE_LOGO_SRC}{match.group('quote')}",
                    body,
                )
                outgoing_values['body'] = body
                company_id = int(company_logo_match.group('company_id'))
                if company_id not in logo_cache:
                    company = self.env['res.company'].sudo().browse(company_id).exists()
                    logo_cache[company_id] = (
                        base64.b64decode(company.logo_web) if company and company.logo_web else None
                    )

            if INLINE_LOGO_SRC not in body:
                continue

            logo_content = logo_cache.get(
                int(company_logo_match.group('company_id')) if company_logo_match else None
            )
            if logo_content is None:
                with file_open(INLINE_LOGO_PATH, mode='rb') as logo_file:
                    logo_content = logo_file.read()
            outgoing_values['attachments'] = [
                *outgoing_values.get('attachments', []),
                (INLINE_LOGO_FILENAME, logo_content, guess_mimetype(logo_content, default='image/png')),
            ]
        return outgoing_list
