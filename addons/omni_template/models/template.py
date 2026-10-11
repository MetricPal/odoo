"""Reusable authoring content. No provider requests, approval or sending."""
import re
from urllib.parse import urlsplit
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.rendering_tools import parse_inline_template

FORMATS = {
    'whatsapp': [('reply', 'Reply'), ('wa_template', 'WhatsApp template')],
    'telegram': [('message', 'Message'), ('photo', 'Photo'), ('video', 'Video'), ('audio', 'Audio'), ('document', 'Document')],
    'slack': [('message', 'Message'), ('card', 'Card')],
    'teams': [('message', 'Message'), ('card', 'Card')],
    'discord': [('message', 'Message'), ('embed', 'Embed')],
    'linkedin': [('post', 'Post'), ('carousel', 'Carousel'), ('public_reply', 'Public reply')],
    'facebook': [('post', 'Post'), ('photo', 'Photo'), ('video', 'Video'), ('public_reply', 'Public reply')],
    'instagram': [('photo', 'Photo'), ('carousel', 'Carousel'), ('reel', 'Reel'), ('story', 'Story'), ('public_reply', 'Public reply'), ('private_reply', 'Private reply')],
    'x': [('post', 'Post'), ('photo', 'Photo'), ('video', 'Video'), ('reply', 'Reply')],
    'tiktok': [('video', 'Video'), ('photo_post', 'Photo post')],
    'youtube': [('video', 'Video')],
    'threads': [('post', 'Post'), ('photo', 'Photo'), ('video', 'Video'), ('reply', 'Reply')],
    'pinterest': [('pin', 'Pin')],
}
MODEL_NAMES = ['res.partner', 'crm.lead', 'sale.order', 'purchase.order', 'account.move', 'project.task', 'helpdesk.ticket']
SELECTION = list(dict(item for formats in FORMATS.values() for item in formats).items())
MEDIA_FORMATS = {'photo', 'video', 'audio', 'document', 'carousel', 'reel', 'story', 'photo_post', 'pin'}
TEXT_FIELDS = ('body', 'title', 'header', 'footer', 'button_label', 'button_url')
PATH = re.compile(r'^(object|company)\.[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*){0,3}$')

def https_url(value):
    try:
        parts = urlsplit(value or '')
        return parts.scheme == 'https' and bool(parts.hostname) and not parts.username and not parts.password and not any(character.isspace() for character in value)
    except ValueError:
        return False


class Template(models.Model):
    _name = 'omni.template'
    _inherit = 'omni.scope.mixin'
    _description = 'Omnichannel Template'
    _order = 'name, id'

    name = fields.Char(required=True, default='New template')
    active = fields.Boolean(default=True)
    channel_type_id = fields.Many2one('omni.channel.type', string='Channel type', required=True, ondelete='restrict')
    channel_code = fields.Char(related='channel_type_id.code')
    content_type = fields.Selection(SELECTION, required=True, default='message', string='Content type')
    format_choices = fields.Json(compute='_compute_format')
    model_name = fields.Selection(selection='_selection_models', string='Applies to', required=True, default='res.partner')
    purpose_id = fields.Many2one('omni.purpose', required=True, ondelete='restrict', string='Communication team',
        default=lambda self: self.env['omni.purpose'].search([] if self.env.user.has_group('base.group_system') else [('user_ids', 'in', [self.env.uid])], limit=1))
    resource_ref = fields.Reference(string='Sample record', selection='_selection_models', copy=False)
    body = fields.Text(string='Message', default='Hi {{ object.name }},\n\nWelcome to {{ company.name }}.')
    title = fields.Char()
    use_header = fields.Boolean(string='Header')
    use_footer = fields.Boolean(string='Footer')
    use_button = fields.Boolean(string='Button')
    header = fields.Char()
    footer = fields.Char()
    button_label = fields.Char(string='Button label')
    button_url = fields.Char(string='Link')
    category = fields.Selection([('UTILITY', 'Utility'), ('MARKETING', 'Marketing'), ('AUTHENTICATION', 'Authentication')], default='UTILITY')
    language_id = fields.Many2one('res.lang', string='Language', domain=[('active', '=', True)], default=lambda self: self.env['res.lang'].search([('code', '=', 'en_US')], limit=1))
    approval_type_id = fields.Many2one('approval.center.policy', string='Approval type', check_company=True,
        help='Suggested policy for a future draft. Saving does not grant approval or override channel policy.')
    media_ids = fields.One2many('omni.template.media', 'template_id', string='Media', copy=True)
    show_media = fields.Boolean(compute='_compute_format')
    show_button = fields.Boolean(compute='_compute_format')
    preview_html = fields.Html(compute='_compute_preview', sanitize=True)
    preview_note = fields.Char(compute='_compute_preview')

    @api.model
    def _optional_values(self, values):
        values = dict(values)
        for flag, names in [('use_header', ('header',)), ('use_footer', ('footer',)), ('use_button', ('button_label', 'button_url'))]:
            if flag in values and not values[flag]:
                values.update(dict.fromkeys(names, False))
            elif flag not in values and any(values.get(name) for name in names):
                values[flag] = True
        return values

    @api.model_create_multi
    def create(self, values):
        return super().create([self._optional_values(item) for item in values])

    def write(self, values):
        return super().write(self._optional_values(values))

    @api.model
    def _selection_models(self):
        return [(name, self.env[name]._description) for name in MODEL_NAMES if name in self.env]

    def _scope(self):
        if not self.env.user.has_group('omni_channel.group_omni_user'):
            raise AccessError(_('Omnichannel access is required.'))
        if self.company_id and self.company_id not in self.env.companies:
            raise AccessError(_('This company is not available.'))
        if self.purpose_id and not self.env.user.has_group('base.group_system') and self.env.user not in self.purpose_id.user_ids:
            raise AccessError(_('This communication team is not available.'))

    @api.depends('channel_code', 'content_type')
    def _compute_format(self):
        for row in self:
            row.format_choices = FORMATS.get(row.channel_code, [])
            row.show_media = row.content_type in MEDIA_FORMATS
            row.show_button = row.content_type == 'wa_template' or row.channel_code == 'telegram' or (row.channel_code in {'slack', 'teams', 'discord'} and row.content_type in {'card', 'embed'})

    @api.onchange('channel_type_id')
    def _onchange_channel(self):
        choices = FORMATS.get(self.channel_code, [])
        self.content_type = choices[0][0] if choices else False
        self.header = self.footer = self.button_label = self.button_url = False
        self.media_ids = [fields.Command.clear()]
        self.title = False
        self.use_header = self.use_footer = self.use_button = False

    @api.onchange('content_type')
    def _onchange_format(self):
        if self.content_type != 'wa_template':
            self.header = self.footer = False
            self.use_header = self.use_footer = False
        if not self.show_button:
            self.button_label = self.button_url = False
            self.use_button = False
        if not self.show_media: self.media_ids = [fields.Command.clear()]
        if self.content_type == 'story': self.body = False

    @api.onchange('use_header', 'use_footer', 'use_button')
    def _onchange_optional(self):
        if not self.use_header: self.header = False
        if not self.use_footer: self.footer = False
        if not self.use_button: self.button_label = self.button_url = False

    @api.onchange('model_name')
    def _onchange_model(self):
        self.resource_ref = False

    def _check_expression(self, expression):
        if not PATH.fullmatch(expression):
            raise ValidationError(_('Use record fields only, for example {{ object.name }}.'))
        root, *parts = expression.split('.')
        if root == 'company':
            if parts != ['name']: raise ValidationError(_('Only company.name is available.'))
            return
        if self.model_name not in MODEL_NAMES or self.model_name not in self.env:
            raise ValidationError(_('Choose a supported business record.'))
        target = self.env[self.model_name]
        for index, part in enumerate(parts):
            metadata = target.fields_get([part])
            field = target._fields.get(part)
            if not metadata or not field or field.type not in {'char', 'text', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime', 'selection', 'many2one'}:
                raise ValidationError(_('This field is not available for templates.'))
            if field.type == 'many2one':
                if index == len(parts)-1 or field.comodel_name not in MODEL_NAMES:
                    raise ValidationError(_('Select a text field from an accessible business record.'))
                target = self.env[field.comodel_name]
            elif index != len(parts)-1:
                raise ValidationError(_('Select a valid field path.'))

    def _check_record(self, record):
        record.check_access('read')
        if 'company_id' in record._fields and record.company_id and record.company_id != self.company_id:
            raise AccessError(_('The sample record belongs to another company.'))

    def _render_text(self, text, resource=None):
        output = []
        for literal, expression, default in parse_inline_template(text or ''):
            output.append(literal)
            default = default.strip()
            if expression:
                expression = expression.strip()
                self._check_expression(expression)
                root, *parts = expression.split('.')
                value = self.company_id if root == 'company' else resource
                if value:
                    value = value.with_context(allowed_company_ids=[self.company_id.id])
                if value:
                    for part in parts:
                        if isinstance(value, models.BaseModel): self._check_record(value)
                        value = value[part] if value else False
                    output.append(str(value or default or ''))
                else:
                    output.append('{{ ' + expression + ' }}')
        return ''.join(output)

    def render_content(self, resource_id):
        """Read-only RPC for future composers; returns a copy, never sends."""
        self.ensure_one()
        self.check_access('read')
        self._scope()
        if type(resource_id) is not int or resource_id <= 0:
            raise ValidationError(_('Choose a sample record.'))
        resource = self.env[self.model_name].browse(resource_id).exists()
        if not resource: raise ValidationError(_('The sample record no longer exists.'))
        self._check_record(resource)
        result = {key: self._render_text(self[key], resource) for key in TEXT_FIELDS}
        if result['button_url'] and not https_url(result['button_url']):
            raise ValidationError(_('The rendered button link must use HTTPS.'))
        result['media'] = [{'id': item.id, 'name': item.name, 'kind': item.kind} for item in self.media_ids.sorted(lambda item: (item.sequence, item.id))]
        result['channel'] = self.channel_code
        result['content_type'] = self.content_type
        return result

    @api.constrains('channel_type_id', 'content_type', 'model_name', 'resource_ref', *TEXT_FIELDS, 'language_id', 'category', 'media_ids')
    def _check_content(self):
        for row in self:
            row._scope()
            if row.model_name not in MODEL_NAMES or row.model_name not in self.env or row.content_type not in dict(FORMATS.get(row.channel_code, [])):
                raise ValidationError(_('Choose a supported channel and content type.'))
            if row.resource_ref and row.resource_ref._name != row.model_name:
                raise ValidationError(_('The sample record must match Applies to.'))
            for key in TEXT_FIELDS:
                if len(row[key] or '') > 20000: raise ValidationError(_('Template content is too long.'))
                row._render_text(row[key])
            if bool(row.button_label) != bool(row.button_url): raise ValidationError(_('Enter both a button label and link.'))
            if row.button_url and '{{' not in row.button_url and not https_url(row.button_url):
                raise ValidationError(_('Button links must use HTTPS.'))
            if row.content_type == 'wa_template' and not row.language_id:
                raise ValidationError(_('Choose a WhatsApp template language.'))
            if row.content_type != 'wa_template' and (row.header or row.footer):
                raise ValidationError(_('Headers and footers are for WhatsApp templates.'))
            if not row.show_button and row.button_label: raise ValidationError(_('Buttons are not available for this content type.'))
            if row.channel_code not in {'youtube', 'pinterest'} and row.title: raise ValidationError(_('Titles are not available for this channel.'))
            if row.media_ids:
                row.media_ids._check_media()
                if row.content_type not in {'carousel', 'photo_post'} and len(row.media_ids) > 1:
                    raise ValidationError(_('This content type uses one media file.'))
                if len(row.media_ids) > 20:
                    raise ValidationError(_('A template supports up to 20 media files.'))
            if row.content_type == 'story' and row.body: raise ValidationError(_('Stories use media without a message.'))

    def _formatted_body(self, body):
        safe = str(escape(body))
        if self.channel_code == 'telegram':
            for tag in ('b', 'i'):
                safe = re.sub('&lt;' + tag + '&gt;(.*?)&lt;/' + tag + '&gt;', r'<' + tag + r'>\1</' + tag + '>', safe, flags=re.S)
        elif self.channel_code in {'whatsapp', 'slack', 'teams', 'discord'}:
            star = r'\*' if self.channel_code in {'whatsapp', 'slack'} else r'\*\*'
            safe = re.sub(star + r'(.+?)' + star, r'<b>\1</b>', safe, flags=re.S)
            safe = re.sub(r'_(.+?)_', r'<i>\1</i>', safe, flags=re.S)
        return Markup(safe)

    @api.depends('resource_ref', 'model_name', 'company_id', 'purpose_id', 'channel_type_id', 'content_type', *TEXT_FIELDS, 'media_ids.name', 'media_ids.kind', 'media_ids.sequence')
    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_preview(self):
        for row in self:
            row.preview_note = _('Preview only. Nothing is sent.')
            try:
                row._scope()
                if row.resource_ref and row.resource_ref._name != row.model_name:
                    raise ValidationError(_('Choose a sample record matching Applies to.'))
                resource = row.resource_ref.exists() if row.resource_ref else None
                if resource: row._check_record(resource)
                rendered = {key: row._render_text(row[key], resource) for key in TEXT_FIELDS}
                chunks = [Markup('<div class="omni_template_message">')]
                for key in ('title', 'header', 'body', 'footer'):
                    if rendered[key]: chunks.append(Markup('<div class="ot_%s">%s</div>') % (key, row._formatted_body(rendered[key]) if key == 'body' else rendered[key]))
                for media in row.media_ids.sorted(lambda item: (item.sequence, item.id if isinstance(item.id, int) else 0)):
                    chunks.append(Markup('<div class="ot_media"><i class="fa fa-paperclip"/> %s · %s</div>') % (media.name or _('Media'), dict(media._fields['kind'].selection)[media.kind]))
                if rendered['button_label']:
                    if not https_url(rendered['button_url']): raise ValidationError(_('The rendered button link must use HTTPS.'))
                    # Preview is inert, so clicking never executes a provider action.
                    chunks.append(Markup('<div class="ot_button">%s ↗</div>') % rendered['button_label'])
                chunks.append(Markup('</div>'))
                row.preview_html = Markup('').join(chunks)
                if row.content_type == 'wa_template':
                    row.preview_note = _('Local draft. Meta submission and approval are not available here.')
                elif not resource: row.preview_note = _('Choose a sample record to fill record fields.')
            except AccessError:
                row.preview_html = False
                row.preview_note = _('This sample record is not available to you.')
            except ValidationError as error:
                row.preview_html = False
                row.preview_note = str(error)

class Media(models.Model):
    _name = 'omni.template.media'
    _description = 'Template Media'
    _order = 'sequence, id'
    _check_company_auto = True
    template_id = fields.Many2one('omni.template', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='template_id.company_id', store=True, precompute=True)
    purpose_id = fields.Many2one(related='template_id.purpose_id', store=True, precompute=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Filename', required=True)
    kind = fields.Selection([('photo', 'Photo'), ('video', 'Video'), ('audio', 'Audio'), ('document', 'Document')], required=True, default='photo')
    content = fields.Binary(required=True, attachment=True, string='File')

    def copy_data(self, default=None):
        values = super().copy_data(default)
        if not default or 'name' not in default:
            for row, data in zip(self, values): data['name'] = row.name
        return values

    @api.constrains('template_id', 'content', 'kind')
    def _check_media(self):
        for row in self:
            row.template_id.check_access('write')
            row.template_id._scope()
            if not row.template_id.show_media: raise ValidationError(_('Choose a media content type first.'))
            if row.content and row.content.size > 64 * 1024 * 1024: raise ValidationError(_('Files must be under 64 MB.'))
            fmt = row.template_id.content_type
            count = len(row.template_id.media_ids)
            maximum = 10 if row.template_id.channel_code == 'instagram' else 20
            if count > maximum or (fmt not in {'carousel', 'photo_post'} and count > 1):
                raise ValidationError(_('Too many media files for this content type.'))
            allowed = {'video'} if fmt in {'reel', 'video'} else {'audio'} if fmt == 'audio' else {'document'} if fmt == 'document' else {'photo', 'video'} if fmt in {'carousel', 'story'} else {'photo'}
            if row.kind not in allowed: raise ValidationError(_('Choose a compatible media type.'))
