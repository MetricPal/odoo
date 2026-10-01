import re
from html import unescape

from markupsafe import escape

from odoo import fields, models, tools
from odoo.tools import file_open
from odoo.tools.mimetypes import guess_mimetype

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_PATH, INLINE_LOGO_SRC


_BRANDING_FOOTER_MARKER = 'data-branding-mail-footer="1"'
_LEFT_CONTENT_MARKER = 'data-branding-content-align="left"'
_BODY_TAG_RE = re.compile(r'<body(?P<attributes>[^>]*)>', flags=re.IGNORECASE)
_LEFT_ALIGNMENT_RE = re.compile(
    r'(?:\balign\s*=\s*["\']?left\b|\btext-align\s*:\s*left\b)',
    flags=re.IGNORECASE,
)
_BACKGROUND_COLOR_RE = re.compile(
    r'\bbackground(?:-color)?\s*:\s*'
    r'(?P<color>#[0-9a-f]{3,8}|rgba?\([^)]{1,50}\)|[a-z]+)',
    flags=re.IGNORECASE,
)
_BGCOLOR_RE = re.compile(
    r'\bbgcolor\s*=\s*["\'](?P<color>#[0-9a-f]{3,8}|[a-z]+)["\']',
    flags=re.IGNORECASE,
)
_UNSUBSCRIBE_HREF_RE = re.compile(
    r'<a\b[^>]*\bhref=(?P<quote>["\'])'
    r'(?P<url>[^"\']*unsubscribe[^"\']*)(?P=quote)',
    flags=re.IGNORECASE,
)
_STYLE_ATTRIBUTE_RE = re.compile(
    r'\bstyle=(?P<quote>["\'])(?P<style>.*?)(?P=quote)',
    flags=re.IGNORECASE | re.DOTALL,
)
_BGCOLOR_ATTRIBUTE_RE = re.compile(
    r'\s+bgcolor=(?P<quote>["\']).*?(?P=quote)',
    flags=re.IGNORECASE | re.DOTALL,
)
_COMPANY_LOGO_IMG_RE = re.compile(
    r'<img\b[^>]*\bsrc=(?P<quote>["\'])'
    r'(?:https?://[^"\']+)?/(?:logo(?:\.png)?|web/binary/company_logo)'
    r'\?[^"\']*\bcompany=\d+[^"\']*(?P=quote)[^>]*>',
    flags=re.IGNORECASE,
)
_INLINE_BRANDING_LOGO_IMG_RE = re.compile(
    rf'<img\b[^>]*\bsrc=["\']{re.escape(INLINE_LOGO_SRC)}["\'][^>]*>',
    flags=re.IGNORECASE,
)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _branding_company(self):
        self.ensure_one()
        return (self.record_company_id or self.env.company).sudo()

    def _branding_footer_html(
        self,
        company,
        alignment='center',
        canvas_color=None,
        unsubscribe_url=None,
    ):
        locality = ' '.join(filter(None, (company.zip, company.city)))
        region = ', '.join(filter(None, (company.state_id.name, company.country_id.name)))
        city_country = ', '.join(filter(None, (locality, region)))
        address_lines = filter(None, (company.street, company.street2, city_country))
        address_html = ''.join(
            f'<div>{escape(address_line)}</div>'
            for address_line in address_lines
        )
        privacy_url = tools.urls.urljoin(self.get_base_url(), 'privacy')
        company_name = escape(company.name or '')
        # Splitting around domain-like punctuation prevents email clients from
        # auto-linking a company name such as "metric.io".
        company_name_html = ''.join(
            f'<span>{escape(part)}</span>'
            for part in re.split(r'([.@])', company.name or '')
            if part
        )
        copyright_year = fields.Date.context_today(self).year
        privacy_url = escape(privacy_url)
        if unsubscribe_url:
            unsubscribe_html = (
                ' &middot; '
                f'<a href="{escape(unescape(unsubscribe_url))}" '
                'style="color:#5f6368; font:inherit; text-decoration:underline;">'
                'Unsubscribe</a>'
            )
        else:
            unsubscribe_html = ''
        if canvas_color:
            canvas_color = escape(canvas_color)
            canvas_attribute = f' bgcolor="{canvas_color}"'
            canvas_style = f'background-color:{canvas_color};'
            spacer_before = '<tr><td height="32" style="height:32px; line-height:32px; font-size:0;">&nbsp;</td></tr>'
            spacer_after = '<tr><td height="20" style="height:20px; line-height:20px; font-size:0;">&nbsp;</td></tr>'
        else:
            canvas_attribute = ''
            canvas_style = 'margin-top:32px;'
            spacer_before = ''
            spacer_after = ''
        return f'''
<table {_BRANDING_FOOTER_MARKER} role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"{canvas_attribute} style="width:100%; {canvas_style} border-collapse:separate;">
    {spacer_before}
    <tr>
        <td data-branding-footer-align="{alignment}" align="{alignment}" style="padding:0; text-align:{alignment};">
            <table role="presentation" align="{alignment}" border="0" cellpadding="0" cellspacing="0" width="600" style="width:100%; max-width:600px; background-color:#eeeeee; border-radius:12px; border-collapse:separate;">
                <tr>
                    <td align="left" style="padding:24px 28px; color:#5f6368; font-family:Verdana, Arial, sans-serif; font-size:11px; font-weight:normal; line-height:16px;">
                        <img src="{INLINE_LOGO_SRC}" alt="{company_name}" width="64" style="display:block; width:64px; max-width:100%; height:auto; margin:0 0 12px 0; border:0;"/>
                        <div data-branding-company-name="1">{company_name_html}</div>
                        <div data-branding-company-address="1" style="margin-top:4px;">{address_html}</div>
                        <div style="margin-top:6px;">
                            <a href="{privacy_url}" style="color:#5f6368; font:inherit; text-decoration:underline;">Privacy</a>{unsubscribe_html}
                        </div>
                        <div data-branding-copyright="1" style="margin-top:16px;">
                            {company_name_html} &copy; {copyright_year}
                        </div>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    {spacer_after}
</table>'''

    @staticmethod
    def _branding_footer_alignment(body):
        if _LEFT_CONTENT_MARKER in body:
            return 'left'
        body_match = _BODY_TAG_RE.search(body)
        if body_match and _LEFT_ALIGNMENT_RE.search(body_match.group('attributes')):
            return 'left'
        return 'center'

    @staticmethod
    def _branding_marketing_canvas_color(body):
        body_match = _BODY_TAG_RE.search(body)
        canvas_html = body[body_match.start():] if body_match else body
        matches = [
            match
            for pattern in (_BACKGROUND_COLOR_RE, _BGCOLOR_RE)
            if (match := pattern.search(canvas_html))
        ]
        if not matches:
            return None
        return min(matches, key=lambda match: match.start()).group('color')

    def _branding_unsubscribe_url(self, body, is_mass_mailing=False):
        if unsubscribe_match := _UNSUBSCRIBE_HREF_RE.search(body):
            return unsubscribe_match.group('url')
        if is_mass_mailing:
            return tools.urls.urljoin(self.get_base_url(), 'unsubscribe_from_list')
        return None

    @staticmethod
    def _branding_force_white_canvas(body):
        def _replace_body(match):
            attributes = match.group('attributes')
            style_match = _STYLE_ATTRIBUTE_RE.search(attributes)
            if style_match:
                style = style_match.group('style').rstrip().rstrip(';')
                replacement = (
                    f'style={style_match.group("quote")}{style}; '
                    f'background-color:#ffffff !important;{style_match.group("quote")}'
                )
                attributes = _STYLE_ATTRIBUTE_RE.sub(replacement, attributes, count=1)
            else:
                attributes += ' style="background-color:#ffffff !important;"'
            attributes = _BGCOLOR_ATTRIBUTE_RE.sub('', attributes)
            return f'<body{attributes} bgcolor="#ffffff">'

        if _BODY_TAG_RE.search(body):
            return _BODY_TAG_RE.sub(_replace_body, body, count=1)
        return (
            '<div style="background-color:#ffffff; color:#454748;">'
            f'{body}'
            '</div>'
        )

    @staticmethod
    def _branding_set_digest_canvas(body):
        def _replace_body(match):
            attributes = match.group('attributes')
            style_match = _STYLE_ATTRIBUTE_RE.search(attributes)
            if style_match:
                style = style_match.group('style').rstrip().rstrip(';')
                if _BACKGROUND_COLOR_RE.search(style):
                    replacement = (
                        f'style={style_match.group("quote")}{style};'
                        f'{style_match.group("quote")}'
                    )
                else:
                    replacement = (
                        f'style={style_match.group("quote")}{style}; '
                        f'background-color:#F9FAFB;{style_match.group("quote")}'
                    )
                attributes = _STYLE_ATTRIBUTE_RE.sub(replacement, attributes, count=1)
            else:
                attributes += ' style="background-color:#F9FAFB;"'
            attributes = _BGCOLOR_ATTRIBUTE_RE.sub('', attributes)
            return f'<body{attributes} bgcolor="#F9FAFB">'

        if _BODY_TAG_RE.search(body):
            return _BODY_TAG_RE.sub(_replace_body, body, count=1)
        return body

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        outgoing_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        company = self._branding_company()
        is_marketing_email = 'mailing_id' in self._fields and bool(self.mailing_id)

        logo_content = company.logo_web.content if company.logo_web else None
        if logo_content is None:
            with file_open(INLINE_LOGO_PATH, mode='rb') as logo_file:
                logo_content = logo_file.read()
        logo_attachment = (
            INLINE_LOGO_FILENAME,
            logo_content,
            guess_mimetype(logo_content, default='image/png'),
        )

        for outgoing_values in outgoing_list:
            body = str(outgoing_values.get('body') or '')
            is_digest_email = 'data-branding-email-kind="digest"' in body
            is_promotional_email = is_marketing_email or is_digest_email
            # Company logos belong in the shared footer, never in an email header.
            body = _COMPANY_LOGO_IMG_RE.sub('', body)
            if _BRANDING_FOOTER_MARKER not in body:
                body = _INLINE_BRANDING_LOGO_IMG_RE.sub('', body)
                alignment = self._branding_footer_alignment(body)
                canvas_color = (
                    self._branding_marketing_canvas_color(body)
                    if is_promotional_email else None
                )
                unsubscribe_url = (
                    self._branding_unsubscribe_url(
                        body,
                        is_mass_mailing=is_marketing_email,
                    )
                    if is_promotional_email else None
                )
                footer_html = self._branding_footer_html(
                    company,
                    alignment=alignment,
                    canvas_color=canvas_color,
                    unsubscribe_url=unsubscribe_url,
                )
                body = tools.mail.append_content_to_html(body, footer_html, plaintext=False)
            if is_digest_email:
                body = self._branding_set_digest_canvas(str(body))
            elif not is_promotional_email:
                body = self._branding_force_white_canvas(str(body))

            outgoing_values['body'] = body
            outgoing_values['body_alternative'] = tools.html2plaintext(body)
            attachments = outgoing_values.get('attachments', [])
            if not any(attachment[0] == INLINE_LOGO_FILENAME for attachment in attachments):
                outgoing_values['attachments'] = [*attachments, logo_attachment]
        return outgoing_list
