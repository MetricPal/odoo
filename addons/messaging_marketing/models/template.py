"""WhatsApp templates (plan M8, board 15.1, approved 2026-11-16).

WhatsApp lets a business start a conversation only with a text Meta has approved. A template is written here with
the same fields as a mailing ({first_name}, {name}), submitted to Meta, and followed until Meta answers. Meta
reviews the template's text once; the company's approver still reviews every mailing that uses it.

The calls to Meta are made by the WhatsApp connector (``omni_whatsapp``) when it is installed; this module never
holds credentials.
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

STATES = [
    ('draft', 'Draft'),
    ('review', 'In review at Meta'),
    ('approved', 'Approved by Meta'),
    ('rejected', 'Rejected by Meta'),
    ('paused', 'Paused by Meta'),
]
# Languages Meta accepts for templates (its codes), the ones a team here is likely to write in.
LANGUAGES = [
    ('en', 'English'), ('en_GB', 'English (UK)'), ('en_US', 'English (US)'), ('ms', 'Malay'),
    ('id', 'Indonesian'), ('zh_CN', 'Chinese (Simplified)'), ('zh_TW', 'Chinese (Traditional)'),
    ('ta', 'Tamil'), ('hi', 'Hindi'), ('ar', 'Arabic'), ('th', 'Thai'), ('vi', 'Vietnamese'),
    ('ja', 'Japanese'), ('ko', 'Korean'), ('fr', 'French'), ('de', 'German'), ('es', 'Spanish'),
    ('pt_BR', 'Portuguese (Brazil)'), ('it', 'Italian'), ('nl', 'Dutch'), ('tr', 'Turkish'), ('ru', 'Russian'),
]
CONTENT = {'name', 'channel_id', 'language', 'header', 'body', 'footer', 'button_label', 'button_url',
           'example_first_name', 'example_name'}
SERVER = {'state', 'meta_id', 'meta_name', 'meta_reason', 'submitted_at', 'checked_at'}
BODY_LIMIT = 1024
FIELD = re.compile(r'\{(first_name|name)\}')


def numbered(text):
    """``(text with Meta's numbered fields, the field of each number)``: 'Hi {first_name}' → 'Hi {{1}}'."""
    order = []

    def replace(match):
        if match.group(1) not in order:
            order.append(match.group(1))
        return '{{%d}}' % (order.index(match.group(1)) + 1)

    return FIELD.sub(replace, text or ''), order


def one_line(value):
    """A value Meta accepts in a numbered field: one line, single spaces."""
    return ' '.join((value or '').split())


class WhatsAppTemplate(models.Model):
    _name = 'mm.whatsapp.template'
    _description = 'WhatsApp template'
    _inherit = ['mail.thread']
    _order = 'name, language, id'

    name = fields.Char(required=True, string='Template', tracking=True,
                       help='For your team; Meta gets a technical name made from it.')
    channel_id = fields.Many2one(
        'omni.channel', string='Send from', required=True, ondelete='restrict', check_company=True,
        domain="[('channel_type_id.code', '=', 'whatsapp')]",
        help='The WhatsApp number whose business account owns this template.')
    company_id = fields.Many2one(related='channel_id.company_id', store=True, precompute=True)
    purpose_id = fields.Many2one(related='channel_id.purpose_id', store=True, precompute=True,
                                 string='Communication team')
    language = fields.Selection(LANGUAGES, required=True, default='en', tracking=True)
    kind = fields.Selection([('marketing', 'Marketing')], default='marketing', required=True, readonly=True,
                            help='Offers, news and greetings. Order updates and codes are not supported yet.')
    header = fields.Char(help='Optional. One short line in bold above the message; no fields.')
    body = fields.Text(string='Message', tracking=True)
    footer = fields.Char(help='Optional. One short grey line under the message, for example how to stop.')
    button_label = fields.Char(string='Button text')
    button_url = fields.Char(string='Button link')
    example_first_name = fields.Char(string='Example first name', default='Sara',
                                     help='Meta asks for an example of each field to review the template.')
    example_name = fields.Char(string='Example name', default='Sara Lim')

    state = fields.Selection(STATES, required=True, default='draft', readonly=True, copy=False, index=True,
                             tracking=True, string='Status')
    meta_name = fields.Char(readonly=True, string="Meta's name", help='The technical name of the template at Meta.')
    meta_id = fields.Char(readonly=True, copy=False, string="Meta's number")
    meta_reason = fields.Char(readonly=True, copy=False, string="Meta's reason")
    submitted_at = fields.Datetime(readonly=True, copy=False, string='Submitted on')
    checked_at = fields.Datetime(readonly=True, copy=False, string='Last checked')

    char_count = fields.Integer(compute='_compute_preview', string='Characters')
    preview_text = fields.Text(compute='_compute_preview')
    uses_first_name = fields.Boolean(compute='_compute_preview')
    uses_name = fields.Boolean(compute='_compute_preview')

    _meta_unique = models.Constraint(
        'UNIQUE(channel_id, meta_name, language)',
        'This template already exists in this language. Open it, or choose another language.')

    @api.depends('name', 'language')
    def _compute_display_name(self):
        languages = dict(self._fields['language']._description_selection(self.env))
        for row in self:
            row.display_name = ' · '.join(filter(None, [row.name, languages.get(row.language)]))

    @api.depends('body', 'example_first_name', 'example_name')
    def _compute_preview(self):
        for row in self:
            body = row.body or ''
            row.uses_first_name = '{first_name}' in body
            row.uses_name = '{name}' in body
            row.preview_text = body.replace('{first_name}', row.example_first_name or '').replace(
                '{name}', row.example_name or '')
            row.char_count = len(row.preview_text)

    # ------------------------------------------------------------------ CRUD

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(SERVER & vals.keys() - {'meta_name'} for vals in vals_list):
            raise AccessError(_("A template's status is recorded from Meta's answer."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if SERVER & vals.keys():
                raise AccessError(_("A template's status is recorded from Meta's answer."))
            if CONTENT & vals.keys() and any(row.state != 'draft' for row in self):
                raise UserError(_('A template cannot be changed once it was submitted to Meta. '
                                  'Make a new draft from it.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(row.state != 'draft' for row in self):
            raise UserError(_('A template that was submitted to Meta is kept. Only drafts can be deleted.'))
        return super().unlink()

    def copy_data(self, default=None):
        default = dict(default or {})
        default.setdefault('meta_name', False)
        return super().copy_data(default)

    @api.constrains('channel_id')
    def _check_channel(self):
        for row in self:
            if row.channel_id.channel_type_id.code != 'whatsapp':
                raise ValidationError(_('Choose a WhatsApp number to send from.'))

    # ------------------------------------------------------------------ the text Meta reviews

    def _problems(self):
        """What must change before Meta can review this template, in the marketer's words."""
        self.ensure_one()
        problems = []
        body = (self.body or '').strip()
        if not body:
            problems.append(_('Write the message.'))
        else:
            if '{' in FIELD.sub('', body) or '}' in FIELD.sub('', body):
                problems.append(_('Only {first_name} and {name} can be used as fields in the message.'))
            if len(self.preview_text or '') > BODY_LIMIT:
                problems.append(_('The message is longer than %s characters.', BODY_LIMIT))
            if FIELD.match(body) or re.search(r'\{(first_name|name)\}$', body):
                problems.append(_('The message cannot start or end with a field: Meta refuses it. '
                                  'Add a word before or after, for example "Hi {first_name},".'))
            if re.search(r'\n{3,}| {4}|\t', body):
                problems.append(_('Remove tabs, runs of spaces and more than one empty line.'))
        for label, value in ((_('header'), self.header), (_('footer'), self.footer)):
            if value and (len(value) > 60 or '{' in value):
                problems.append(_('The %s is one line of at most 60 characters, without fields.', label))
        if bool(self.button_label) != bool(self.button_url):
            problems.append(_('A button needs both a text and a link.'))
        elif self.button_label:
            if len(self.button_label) > 25:
                problems.append(_('The button text is at most 25 characters.'))
            if not re.fullmatch(r'https://[^\s{}]+', self.button_url or ''):
                problems.append(_('The button link starts with https:// and has no spaces or fields.'))
        if self.uses_first_name and not one_line(self.example_first_name):
            problems.append(_('Give an example first name: Meta asks for one.'))
        if self.uses_name and not one_line(self.example_name):
            problems.append(_('Give an example name: Meta asks for one.'))
        return problems

    def _values(self, contact):
        """The value of each numbered field for one person, in Meta's order."""
        self.ensure_one()
        name = one_line(contact.name) or '-'
        first = name.split()[0]
        return [first if field == 'first_name' else name for field in numbered(self.body)[1]]

    def _account(self):
        """The WhatsApp business account behind "Send from", for the connector's calls."""
        self.ensure_one()
        account = self.channel_id.sudo().selected_sender_id.account_id
        if not account or not hasattr(account, '_whatsapp_template_submit'):
            raise UserError(_('This number cannot send yet. An Omnichannel administrator connects the WhatsApp '
                              'number and selects its sender.'))
        return account

    # ------------------------------------------------------------------ actions

    def action_submit(self):
        """Submit to Meta: one request; Meta's answer (often "in review") is recorded."""
        self.ensure_one()
        self.check_access('write')
        if self.state != 'draft':
            raise UserError(_('This template was already submitted.'))
        problems = self._problems()
        if problems:
            raise UserError('\n'.join(problems))
        account = self._account()
        text, order = numbered(self.body.strip())
        example = [one_line(self.example_first_name if field == 'first_name' else self.example_name)
                   for field in order]
        name = self.meta_name or self._new_meta_name()
        answer = account._whatsapp_template_submit(
            name=name, language=self.language, body=text, example=example, header=one_line(self.header),
            footer=one_line(self.footer), button_label=one_line(self.button_label),
            button_url=(self.button_url or '').strip())
        self.sudo().write({'meta_name': name, 'meta_id': answer['id'] or False, 'state': answer['status'],
                           'meta_reason': False, 'submitted_at': fields.Datetime.now(),
                           'checked_at': fields.Datetime.now()})
        return True

    def _new_meta_name(self):
        slug = re.sub(r'[^a-z0-9]+', '_', (self.name or '').lower()).strip('_')[:60] or 'template'
        return f'{slug}_{self.id}'

    def action_copy_language(self):
        """The same template in another language: a new draft that keeps Meta's name."""
        self.ensure_one()
        used = self.search([('channel_id', '=', self.channel_id.id), ('meta_name', '=', self.meta_name)]).mapped(
            'language') if self.meta_name else [self.language]
        free = next((code for code, _label in LANGUAGES if code not in used), False)
        if not free:
            raise UserError(_('This template exists in every language already.'))
        copy = self.copy({'name': self.name, 'language': free,
                          'meta_name': self.meta_name or self._new_meta_name()})
        if not self.meta_name:
            self.sudo().write({'meta_name': copy.meta_name})
        return copy._open(_('Choose the language and translate the text.'))

    def action_new_draft(self):
        """Edit as a new draft: Meta keeps the old one, so the new text gets a new name at Meta."""
        self.ensure_one()
        return self.copy({'name': self.name})._open()

    def _open(self, hint=False):
        action = {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                  'view_mode': 'form', 'target': 'current'}
        if hint:
            self.message_post(body=hint)
        return action

    def action_update_from_meta(self):
        """Read the status of the templates now (all of them from the list button, these from a form)."""
        templates = self or self.search([])
        templates.check_access('read')
        failed = templates.sudo()._update_from_meta()
        if failed:
            raise UserError(_('Meta could not be reached for: %s. Try again in a moment.', ', '.join(failed)))
        return True

    @api.model
    def _cron_update_from_meta(self):
        self.sudo().search([('state', 'in', ('review', 'approved', 'paused'))])._update_from_meta()

    def _update_from_meta(self):
        """Record Meta's current answer on each submitted template. Returns the numbers that failed to answer."""
        failed = []
        now = fields.Datetime.now()
        for channel in self.filtered('meta_name').channel_id:
            rows = self.filtered(lambda row: row.channel_id == channel and row.meta_name)
            account = channel.selected_sender_id.account_id
            if not account or not hasattr(account, '_whatsapp_template_list'):
                failed.append(channel.display_name)
                continue
            try:
                found = {(item['name'], item['language']): item for item in account._whatsapp_template_list()}
            except UserError:
                failed.append(channel.display_name)
                continue
            for row in rows:
                item = found.get((row.meta_name, row.language))
                if not item:
                    if row.state == 'review' and not row.meta_id:
                        # The submission got no clear answer, and Meta does not have it: it never arrived.
                        row.write({'state': 'draft', 'checked_at': now,
                                   'meta_reason': _('Meta did not receive it. Submit it again.')})
                        row._notify_answer()
                    else:
                        row.write({'checked_at': now})
                    continue
                values = {'checked_at': now, 'meta_id': item['id']}
                if item['status'] != row.state:
                    values.update(state=item['status'], meta_reason=item['reason'] or False)
                row.write(values)
                if 'state' in values:
                    row._notify_answer()
        return failed

    def _notify_answer(self):
        """Tell the person who wrote the template what Meta answered."""
        self.ensure_one()
        label = dict(self._fields['state']._description_selection(self.env))[self.state]
        body = _('%(status)s: %(template)s', status=label, template=self.display_name)
        if self.state in ('rejected', 'draft') and self.meta_reason:
            body += ' ' + _("Meta's reason: %s", self.meta_reason)
        self.message_post(body=body, partner_ids=self.create_uid.partner_id.ids,
                          subtype_xmlid='mail.mt_comment')
