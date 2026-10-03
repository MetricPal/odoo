import re
from html import unescape

from markupsafe import escape

from odoo import fields, models, tools
from odoo.tools import file_open
from odoo.tools.mimetypes import guess_mimetype

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_PATH, INLINE_LOGO_SRC


_BRANDING_FOOTER_MARKER = 'data-branding-mail-footer="1"'
_LEFT_CONTENT_MARKER = 'data-branding-content-align="left"'
_CENTER_CONTENT_MARKER = 'data-branding-content-align="center"'
_BRANDING_CONTENT_WIDTH = '590'
_BRANDING_RADIUS = '12px'
_BRANDING_BORDER_COLOR = '#eeeeee'
_DEFAULT_BODY_BACKGROUND = '#F7F8FA'
_DEFAULT_CONTENT_BACKGROUND = '#FFFFFF'
_DEFAULT_FOOTER_BACKGROUND = '#EEEEEE'
_RTL_LANG_CODES = {'ar', 'fa', 'he', 'ur'}
_HEX_COLOR_RE = re.compile(r'^#[0-9a-f]{6}$', flags=re.IGNORECASE)
_BODY_TAG_RE = re.compile(r'<body(?P<attributes>[^>]*)>', flags=re.IGNORECASE)
_LEFT_ALIGNMENT_RE = re.compile(
    r'(?:\balign\s*=\s*["\']?left\b|\btext-align\s*:\s*left\b)',
    flags=re.IGNORECASE,
)
_CENTERED_CONTENT_RE = re.compile(
    r'(?:\balign\s*=\s*["\']?center\b|\btext-align\s*:\s*center\b)',
    flags=re.IGNORECASE,
)
_RTL_DIRECTION_RE = re.compile(
    r'(?:\bdir\s*=\s*["\']?rtl\b|\bdirection\s*:\s*rtl\b)',
    flags=re.IGNORECASE,
)
_LANG_ATTRIBUTE_RE = re.compile(
    r'\blang\s*=\s*["\']?(?P<lang>[a-z]{2,3}(?:[-_][a-z0-9]+)?)',
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
_ALIGN_ATTRIBUTE_RE = re.compile(
    r'\s+align=(?P<quote>["\']?).*?(?P=quote)(?=\s|>)',
    flags=re.IGNORECASE | re.DOTALL,
)
_WIDTH_ATTRIBUTE_RE = re.compile(
    r'\s+width=(?P<quote>["\']?)(?:590|600)(?P=quote)',
    flags=re.IGNORECASE | re.DOTALL,
)
_FIRST_TABLE_RE = re.compile(r'<table\b[^>]*>', flags=re.IGNORECASE | re.DOTALL)
_MAGIC_LINK_EMAIL_RE = re.compile(
    r'(?:/auth/magic-login\b|A\s+sign-in\s+link\s+was\s+requested)',
    flags=re.IGNORECASE,
)
_EMAIL_CONTENT_TABLE_RE = re.compile(
    r'<table\b(?=[^>]*(?:\bwidth\s*=\s*["\']?(?:590|600)\b|'
    r'\bclass\s*=\s*["\'][^"\']*\bglobal_layout\b))[^>]*>',
    flags=re.IGNORECASE | re.DOTALL,
)
_TABLE_ROW_DIVIDER_BEFORE_LEGACY_FOOTER_RE = re.compile(
    r'\s*<tr>\s*<td\b[^>]*>\s*'
    r'<hr\b[^>]*>\s*'
    r'</td>\s*</tr>\s*'
    r'(?=<tr>\s*<td\b[^>]*>\s*<table\b'
    r'(?=[^>]*\bwidth\s*=\s*["\']?590\b)'
    r'(?=[^>]*font-size\s*:\s*11px))',
    flags=re.IGNORECASE | re.DOTALL,
)
_TABLE_ROW_DIVIDER_RE = re.compile(
    r'\s*<tr>\s*<td\b[^>]*>\s*'
    r'<hr\b[^>]*>\s*'
    r'</td>\s*</tr>\s*',
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
_POWERED_BY_ODOO_BLOCK_RE = re.compile(
    r'<(?P<tag>p|div)\b[^>]*>'
    r'(?:(?!</(?P=tag)>).)*?'
    r'\bPower(?:ed)?\s+by\b'
    r'(?:(?!</(?P=tag)>).)*?'
    r'(?:odoo\.com|>\s*Odoo\s*<|>\s*Odoo\s*</a>|Odoo)'
    r'(?:(?!</(?P=tag)>).)*?'
    r'</(?P=tag)>',
    flags=re.IGNORECASE | re.DOTALL,
)
_POWERED_BY_ODOO_INLINE_RE = re.compile(
    r'\bPower(?:ed)?\s+by\s+'
    r'(?:<a\b[^>]*\bodoo\.com[^>]*>\s*Odoo\s*</a>|Odoo)\.?',
    flags=re.IGNORECASE | re.DOTALL,
)
_SENT_BY_BRAND_BLOCK_RE = re.compile(
    r'<(?P<tag>p|div)\b[^>]*>'
    r'(?:(?!</(?P=tag)>).)*?'
    r'\bSent\s+by\b'
    r'(?:(?!</(?P=tag)>).)*?'
    r'(?:metric\.io|YourCompany|<a\b[^>]*>[^<]*</a>)'
    r'(?:(?!</(?P=tag)>).)*?'
    r'</(?P=tag)>',
    flags=re.IGNORECASE | re.DOTALL,
)
_SENT_BY_BRAND_INLINE_RE = re.compile(
    r'\bSent\s+by\s+'
    r'(?:<a\b[^>]*>[^<]*(?:metric\.io|YourCompany)[^<]*</a>|metric\.io|YourCompany)\.?',
    flags=re.IGNORECASE | re.DOTALL,
)
_SENT_BY_BRAND_TABLE_RE = re.compile(
    r'\s*(?:<!--\s*FOOTER BY\s*-->\s*)?'
    r'<tr>\s*<td\b[^>]*>\s*'
    r'(?:<t\b[^>]*>\s*)?'
    r'<table\b[^>]*>'
    r'(?:(?!</table>).)*?'
    r'\bSent\s+by\b'
    r'(?:(?!</table>).)*?'
    r'</table>\s*'
    r'(?:</t>\s*)?'
    r'</td>\s*</tr>\s*',
    flags=re.IGNORECASE | re.DOTALL,
)
_LEGACY_COMPANY_FOOTER_TABLE_RE = re.compile(
    r'\s*<tr>\s*<td\b[^>]*>\s*'
    r'<table\b(?=[^>]*\bwidth\s*=\s*["\']?590\b)(?=[^>]*font-size\s*:\s*11px)[^>]*>'
    r'(?P<content>(?:(?!</table>).)*?)'
    r'</table>\s*</td>\s*</tr>\s*',
    flags=re.IGNORECASE | re.DOTALL,
)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _branding_company(self):
        self.ensure_one()
        return (self.record_company_id or self.env.company).sudo()

    def _branding_footer_html(
        self,
        company,
        alignment='left',
        content_alignment='left',
        direction='ltr',
        canvas_color=None,
        footer_background_color=None,
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
            canvas_style = 'margin-top:0; margin-bottom:32px; display: inline-table;'
            spacer_before = ''
            spacer_after = ''
        image_margin = '0 0 12px auto' if direction == 'rtl' else '0 0 12px 0'
        return f'''
<table {_BRANDING_FOOTER_MARKER} role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"{canvas_attribute} style="width:100%; {canvas_style} border-collapse:separate;">
    {spacer_before}
    <tr>
        <td data-branding-footer-align="{alignment}" align="{alignment}" style="padding:0; text-align:{alignment};">
            <table role="presentation" align="{alignment}" border="0" cellpadding="0" cellspacing="0" width="{_BRANDING_CONTENT_WIDTH}" style="width:100%; max-width:{_BRANDING_CONTENT_WIDTH}px; background-color:{footer_background_color or _DEFAULT_FOOTER_BACKGROUND}; border-radius:{_BRANDING_RADIUS}; border-collapse:separate;">
                <tr>
                    <td dir="{direction}" align="{content_alignment}" style="padding:24px 28px; color:#5f6368; font-family:Verdana, Arial, sans-serif; font-size:11px; font-weight:normal; line-height:16px; text-align:{content_alignment};">
                        <img src="{INLINE_LOGO_SRC}" alt="{company_name}" width="64" style="display:block; width:64px; max-width:100%; height:auto; margin:{image_margin}; border:0;"/>
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
    def _branding_lang_is_rtl(lang):
        return bool(lang) and lang.split('_', 1)[0].split('-', 1)[0].lower() in _RTL_LANG_CODES

    @staticmethod
    def _branding_color(value, fallback):
        value = (value or '').strip()
        return value if _HEX_COLOR_RE.fullmatch(value) else fallback

    def _branding_email_colors(self, company):
        return {
            'body': self._branding_color(
                company.email_body_background_color,
                _DEFAULT_BODY_BACKGROUND,
            ),
            'content': self._branding_color(
                company.email_content_background_color,
                _DEFAULT_CONTENT_BACKGROUND,
            ),
            'footer': self._branding_color(
                company.email_footer_background_color,
                _DEFAULT_FOOTER_BACKGROUND,
            ),
        }

    @staticmethod
    def _branding_style_set(style, **properties):
        style = (style or '').strip()
        for property_name, value in properties.items():
            css_name = property_name.replace('_', '-')
            pattern = re.compile(
                rf'(?P<prefix>^|;)\s*{re.escape(css_name)}\s*:\s*[^;]*;?',
                flags=re.IGNORECASE,
            )
            replacement = rf'\g<prefix> {css_name}:{value};'
            if pattern.search(style):
                style = pattern.sub(replacement, style, count=1)
            else:
                style = f'{style.rstrip().rstrip(";")}; {css_name}:{value};' if style else f'{css_name}:{value};'
        return style.strip()

    @staticmethod
    def _branding_style_remove(style, *property_names):
        style = (style or '').strip()
        for property_name in property_names:
            css_name = property_name.replace('_', '-')
            pattern = re.compile(
                rf'(?P<prefix>^|;)\s*{re.escape(css_name)}\s*:\s*[^;]*;?',
                flags=re.IGNORECASE,
            )
            style = pattern.sub(r'\g<prefix>', style)
        parts = [part.strip() for part in style.split(';') if part.strip()]
        return '; '.join(parts)

    @staticmethod
    def _branding_tag_set_style(tag, **properties):
        style_match = _STYLE_ATTRIBUTE_RE.search(tag)
        if style_match:
            style = MailMail._branding_style_set(style_match.group('style'), **properties)
            replacement = f'style={style_match.group("quote")}{style}{style_match.group("quote")}'
            tag = _STYLE_ATTRIBUTE_RE.sub(replacement, tag, count=1)
        else:
            style = MailMail._branding_style_set('', **properties)
            tag = f'{tag[:-1]} style="{style}">'
        return tag

    @staticmethod
    def _branding_tag_remove_style_properties(tag, *property_names):
        style_match = _STYLE_ATTRIBUTE_RE.search(tag)
        if not style_match:
            return tag
        style = MailMail._branding_style_remove(style_match.group('style'), *property_names)
        replacement = f'style={style_match.group("quote")}{style}{style_match.group("quote")}'
        return _STYLE_ATTRIBUTE_RE.sub(replacement, tag, count=1)

    @staticmethod
    def _branding_tag_remove_bgcolor(tag):
        return _BGCOLOR_ATTRIBUTE_RE.sub('', tag, count=1)

    @staticmethod
    def _branding_tag_set_bgcolor(tag, color):
        if _BGCOLOR_ATTRIBUTE_RE.search(tag):
            return _BGCOLOR_ATTRIBUTE_RE.sub(f' bgcolor="{color}"', tag, count=1)
        return f'{tag[:-1]} bgcolor="{color}">'

    @staticmethod
    def _branding_tag_set_width(tag):
        if _WIDTH_ATTRIBUTE_RE.search(tag):
            return _WIDTH_ATTRIBUTE_RE.sub(f' width="{_BRANDING_CONTENT_WIDTH}"', tag, count=1)
        return tag

    @staticmethod
    def _branding_tag_set_align(tag, alignment):
        if _ALIGN_ATTRIBUTE_RE.search(tag):
            return _ALIGN_ATTRIBUTE_RE.sub(f' align="{alignment}"', tag, count=1)
        return f'{tag[:-1]} align="{alignment}">'

    def _branding_set_first_table_background(self, body, background_color):
        if not body.lstrip().lower().startswith('<table'):
            return body

        def _replace(match):
            tag = self._branding_tag_set_style(match.group(0), background_color=background_color)
            return self._branding_tag_set_bgcolor(tag, background_color)

        return _FIRST_TABLE_RE.sub(_replace, body, count=1)

    def _branding_style_email_content(self, body, content_background_color=None, table_alignment='center'):
        def _replace(match):
            tag = match.group(0)
            style_match = _STYLE_ATTRIBUTE_RE.search(tag)
            style = style_match.group('style') if style_match else ''
            has_border = (
                re.search(
                    r'(?:^|;)\s*border(?:-(?:top|right|bottom|left))?\s*:',
                    style,
                    flags=re.IGNORECASE,
                )
                or re.search(r'\bclass\s*=\s*["\'][^"\']*\bglobal_layout\b', tag, flags=re.IGNORECASE)
            )
            properties = {
                'border_collapse': 'separate',
            }
            if content_background_color:
                properties['background_color'] = content_background_color
            if has_border:
                properties.update({
                    'border': f'1px solid {_BRANDING_BORDER_COLOR}',
                    'border_radius': _BRANDING_RADIUS,
                    'overflow': 'hidden',
                })
            tag = self._branding_tag_set_style(tag, **properties)
            if not content_background_color:
                tag = self._branding_tag_remove_style_properties(tag, 'background', 'background_color')
                tag = self._branding_tag_remove_bgcolor(tag)
            tag = self._branding_tag_set_width(tag)
            tag = self._branding_tag_set_align(tag, table_alignment)
            if content_background_color:
                tag = self._branding_tag_set_bgcolor(tag, content_background_color)
            return tag

        return _EMAIL_CONTENT_TABLE_RE.sub(_replace, body)

    def _branding_style_email_surfaces(self, body, colors, direction='ltr', content_background=True):
        body = self._branding_set_first_table_background(body, colors['body'])
        table_alignment = 'right' if direction == 'rtl' else 'center'
        content_color = colors['content'] if content_background else None
        return self._branding_style_email_content(body, content_color, table_alignment=table_alignment)

    def _branding_body_direction(self, body):
        if _RTL_DIRECTION_RE.search(body):
            return 'rtl'
        if self._branding_lang_is_rtl(self.env.context.get('lang')):
            return 'rtl'
        for lang_match in _LANG_ATTRIBUTE_RE.finditer(body):
            if self._branding_lang_is_rtl(lang_match.group('lang')):
                return 'rtl'
        return 'ltr'

    @staticmethod
    def _branding_footer_alignment(body, direction='ltr'):
        if direction == 'rtl':
            return 'right'
        if _CENTER_CONTENT_MARKER in body:
            return 'center'
        if _LEFT_CONTENT_MARKER in body:
            return 'left'
        body_match = _BODY_TAG_RE.search(body)
        if body_match and _LEFT_ALIGNMENT_RE.search(body_match.group('attributes')):
            return 'left'
        stripped_body = body.lstrip()
        if stripped_body.lower().startswith('<table'):
            return 'center'
        if body_match and _CENTERED_CONTENT_RE.search(body_match.group('attributes')):
            return 'center'
        if _CENTERED_CONTENT_RE.search(body[:2000]):
            return 'center'
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
    def _branding_remove_odoo_powered_by(body):
        body = _POWERED_BY_ODOO_BLOCK_RE.sub('', body)
        return _POWERED_BY_ODOO_INLINE_RE.sub('', body)

    @staticmethod
    def _branding_remove_sent_by_brand(body):
        body = _SENT_BY_BRAND_TABLE_RE.sub('', body)
        body = _SENT_BY_BRAND_BLOCK_RE.sub('', body)
        return _SENT_BY_BRAND_INLINE_RE.sub('', body)

    @staticmethod
    def _branding_remove_legacy_company_footer(body, company):
        company_name = company.name or ''
        company_website = company.website or ''
        company_email = company.email or ''

        def _replace(match):
            content = match.group('content')
            footer_hints = [
                hint for hint in (company_name, company_website, company_email)
                if hint
            ]
            if any(escape(hint) in content or hint in content for hint in footer_hints):
                return ''
            return match.group(0)

        return _LEGACY_COMPANY_FOOTER_TABLE_RE.sub(_replace, body)

    @staticmethod
    def _branding_remove_magic_link_bottom_divider(body):
        body = _TABLE_ROW_DIVIDER_BEFORE_LEGACY_FOOTER_RE.sub('', body)
        divider_matches = list(_TABLE_ROW_DIVIDER_RE.finditer(body))
        if len(divider_matches) <= 1:
            return body
        pieces = []
        cursor = 0
        for index, match in enumerate(divider_matches):
            pieces.append(body[cursor:match.start()])
            if index == 0:
                pieces.append(match.group(0))
            cursor = match.end()
        pieces.append(body[cursor:])
        return ''.join(pieces)

    @staticmethod
    def _branding_append_footer_to_canvas(body, footer_html, canvas_color):
        if not canvas_color:
            return None
        stripped_body = body.lstrip()
        if not stripped_body.lower().startswith('<table'):
            return None
        insert_at = body.lower().rfind('</table>')
        if insert_at == -1:
            return None
        canvas_color = escape(canvas_color)
        footer_row = (
            f'<tr><td align="center" bgcolor="{canvas_color}" '
            f'style="background-color:{canvas_color};">'
            f'{footer_html}'
            '</td></tr>'
        )
        return f'{body[:insert_at]}{footer_row}{body[insert_at:]}'

    @staticmethod
    def _branding_force_body_canvas(body, background_color):
        def _replace_body(match):
            attributes = match.group('attributes')
            style_match = _STYLE_ATTRIBUTE_RE.search(attributes)
            if style_match:
                style = style_match.group('style').rstrip().rstrip(';')
                replacement = (
                    f'style={style_match.group("quote")}'
                    f'{MailMail._branding_style_set(style, background_color=f"{background_color} !important")}'
                    f'{style_match.group("quote")}'
                )
                attributes = _STYLE_ATTRIBUTE_RE.sub(replacement, attributes, count=1)
            else:
                attributes += f' style="background-color:{background_color} !important;"'
            attributes = _BGCOLOR_ATTRIBUTE_RE.sub('', attributes)
            return f'<body{attributes} bgcolor="{background_color}">'

        if _BODY_TAG_RE.search(body):
            return _BODY_TAG_RE.sub(_replace_body, body, count=1)
        return (
            f'<div style="background-color:{background_color}; color:#454748;">'
            f'{body}'
            '</div>'
        )

    @staticmethod
    def _branding_set_digest_canvas(body, background_color):
        def _replace_body(match):
            attributes = match.group('attributes')
            style_match = _STYLE_ATTRIBUTE_RE.search(attributes)
            if style_match:
                style = style_match.group('style').rstrip().rstrip(';')
                if _BACKGROUND_COLOR_RE.search(style):
                    replacement = (
                        f'style={style_match.group("quote")}'
                        f'{MailMail._branding_style_set(style, background_color=background_color)}'
                        f'{style_match.group("quote")}'
                    )
                else:
                    replacement = (
                        f'style={style_match.group("quote")}{style}; '
                        f'background-color:{background_color};{style_match.group("quote")}'
                    )
                attributes = _STYLE_ATTRIBUTE_RE.sub(replacement, attributes, count=1)
            else:
                attributes += f' style="background-color:{background_color};"'
            attributes = _BGCOLOR_ATTRIBUTE_RE.sub('', attributes)
            return f'<body{attributes} bgcolor="{background_color}">'

        if _BODY_TAG_RE.search(body):
            return _BODY_TAG_RE.sub(_replace_body, body, count=1)
        return body

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        outgoing_list = super()._prepare_outgoing_list(
            mail_server=mail_server,
            doc_to_followers=doc_to_followers,
        )
        company = self._branding_company()
        colors = self._branding_email_colors(company)
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
            is_magic_link_email = bool(_MAGIC_LINK_EMAIL_RE.search(body))
            # Company logos belong in the shared footer, never in an email header.
            body = _COMPANY_LOGO_IMG_RE.sub('', body)
            body = self._branding_remove_odoo_powered_by(body)
            body = self._branding_remove_sent_by_brand(body)
            if is_magic_link_email:
                body = self._branding_remove_magic_link_bottom_divider(body)
            body = self._branding_remove_legacy_company_footer(body, company)
            direction = self._branding_body_direction(body)
            body = self._branding_style_email_surfaces(
                body,
                colors,
                direction=direction,
                content_background=not is_magic_link_email,
            )
            if _BRANDING_FOOTER_MARKER not in body:
                body = _INLINE_BRANDING_LOGO_IMG_RE.sub('', body)
                alignment = self._branding_footer_alignment(body, direction=direction)
                canvas_color = colors['body'] or self._branding_marketing_canvas_color(body)
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
                    content_alignment='right' if direction == 'rtl' else 'left',
                    direction=direction,
                    canvas_color=canvas_color if is_promotional_email else None,
                    footer_background_color=colors['footer'],
                    unsubscribe_url=unsubscribe_url,
                )
                body = (
                    None if is_promotional_email
                    else self._branding_append_footer_to_canvas(
                        body,
                        footer_html,
                        canvas_color,
                    )
                ) or tools.mail.append_content_to_html(body, footer_html, plaintext=False)
            if is_digest_email:
                body = self._branding_set_digest_canvas(str(body), colors['body'])
            elif not is_promotional_email:
                body = self._branding_force_body_canvas(str(body), colors['body'])

            outgoing_values['body'] = body
            outgoing_values['body_alternative'] = tools.html2plaintext(body)
            attachments = outgoing_values.get('attachments', [])
            if not any(attachment[0] == INLINE_LOGO_FILENAME for attachment in attachments):
                outgoing_values['attachments'] = [*attachments, logo_attachment]
        return outgoing_list
