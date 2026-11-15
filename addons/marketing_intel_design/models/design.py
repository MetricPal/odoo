"""Design studio, step 3a (plan M6, approved boards 13.1 to 13.4, 2026-11-15).

A marketing person makes a post, carousel, story, poster or email header without leaving metric.io: they pick a
format and a template, fill the template's texts and picture, and the picture is drawn with the brand kit. Nothing
can be moved or resized (that is the free editor, later). A design is exported as PNG or PDF, or used in a social
post, an email or a proof; nothing is sent or published from here.
"""

import io
import json
import re
import zipfile

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import BinaryBytes

from . import render
from .brand import raw
from odoo.addons.marketing_intel_writing.models import writing

FORMATS = [(key, values[0]) for key, values in render.FORMATS.items()]
LOOKS = [('main', 'Main'), ('light', 'Light'), ('dark', 'Dark')]
LIMITS = {'headline': 60, 'text': 160, 'button': 24}
RUNNING = ('queued', 'submitting', 'running', 'stop_requested')
PREVIEW_WIDTH = 520

# Writing tools (✦) on the texts of the slide being edited, with the box's count.
for _name, _limit in LIMITS.items():
    writing.TARGETS['mi.design', 'slide_' + _name] = 'design_' + _name
    writing.COUNTS['design_' + _name] = {'limit': _limit}


class DesignTemplate(models.Model):
    _name = 'mi.design.template'
    _description = 'Design template'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection([(code, code) for code in render.TEMPLATES], required=True, string='Layout')
    sequence = fields.Integer(default=10)
    description = fields.Char(translate=True)

    def _sample(self, fmt, brand, width=220):
        """The tile of the New design dialog: this template in ``fmt`` with the brand kit."""
        self.ensure_one()
        kit = brand._kit() if brand else {}
        spec = dict(kit, size=render.size_of(fmt), template=self.code, look='main', headline=_('Headline'),
                    text=_('Text'), button=_('Button'), index=1 if self.code == 'tips' else 0,
                    count=3 if self.code == 'tips' else 1)
        return render.png(render.render(spec, width))


class Design(models.Model):
    _name = 'mi.design'
    _description = 'Design'
    _order = 'write_date desc, id desc'

    name = fields.Char(required=True)
    format = fields.Selection(FORMATS, required=True, default='square')
    paper = fields.Selection([('a4', 'A4'), ('a3', 'A3')], default='a4', required=True, string='Poster size')
    format_label = fields.Char(compute='_compute_format_label', string='Size')
    template_id = fields.Many2one('mi.design.template', string='Template', required=True, ondelete='restrict')
    plan_id = fields.Many2one('mi.plan', string='Campaign', ondelete='set null', index=True)
    brand_id = fields.Many2one('mi.brand', string='Brand', required=True, ondelete='cascade', index=True,
                               default=lambda self: self._default_brand())
    company_id = fields.Many2one(related='brand_id.company_id', store=True, index=True)
    user_id = fields.Many2one('res.users', string='Made by', default=lambda self: self.env.user, required=True,
                              readonly=True, index=True, copy=False)
    kit_empty = fields.Boolean(related='brand_id.kit_empty')
    # Set whenever a slide changes, so the design's pictures (cached by its write date) are fetched again.
    touched_at = fields.Datetime(readonly=True, copy=False)
    slide_ids = fields.One2many('mi.design.slide', 'design_id', string='Slides', copy=True)
    slide_count = fields.Integer(compute='_compute_slide_count')
    summary = fields.Char(compute='_compute_summary')
    # The slide being edited: its fields are edited on the design's form, next to the preview.
    active_slide_id = fields.Many2one('mi.design.slide', string='Slide', copy=False, ondelete='set null',
                                      domain="[('design_id', '=', id)]")
    slide_label = fields.Char(compute='_compute_slide_label')
    slide_headline = fields.Char(related='active_slide_id.headline', readonly=False, string='Headline')
    slide_text = fields.Text(related='active_slide_id.text', readonly=False, string='Text')
    slide_button = fields.Char(related='active_slide_id.button', readonly=False, string='Button text')
    slide_image = fields.Image(related='active_slide_id.image', readonly=False, string='Picture')
    slide_look = fields.Selection(related='active_slide_id.look', readonly=False, string='Colours', required=True)
    slide_suggested_headline = fields.Char(related='active_slide_id.suggested_headline')
    slide_suggested_text = fields.Text(related='active_slide_id.suggested_text')
    slide_suggested_button = fields.Char(related='active_slide_id.suggested_button')
    preview = fields.Image(compute='_compute_preview')
    preview_label = fields.Char(compute='_compute_slide_label')
    thumbnail = fields.Image(compute='_compute_thumbnail')
    strip = fields.Html(compute='_compute_strip', sanitize=False)
    use_targets = fields.Char(compute='_compute_use_targets')
    # ✦ Suggest text for all slides
    suggest_state = fields.Selection([('asking', 'Asking'), ('failed', 'Failed')], readonly=True, copy=False)
    suggest_error = fields.Char(readonly=True, copy=False)
    suggest_run_id = fields.Many2one('ai.agent.run', readonly=True, copy=False)
    suggest_asked_at = fields.Datetime(readonly=True, copy=False)

    # ------------------------------------------------------------------ what the form shows

    @api.model
    def _default_brand(self):
        plan = self.env['mi.plan'].browse(self.env.context.get('default_plan_id')).exists()
        return plan.brand_id or self.env['mi.brand'].search([], limit=1)

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id:
            self.brand_id = self.plan_id.brand_id

    @api.depends('format', 'paper')
    def _compute_format_label(self):
        labels = dict(self._fields['format']._description_selection(self.env))
        for design in self:
            if design.format == 'poster':
                design.format_label = '%s · %s' % (labels['poster'], design.paper.upper())
            elif design.format:
                width, height = render.size_of(design.format)
                design.format_label = '%s · %s × %s' % (labels[design.format], width, height)
            else:
                design.format_label = ''

    @api.depends('slide_ids')
    def _compute_slide_count(self):
        for design in self:
            design.slide_count = len(design.slide_ids)

    @api.depends('format', 'paper', 'slide_ids', 'plan_id')
    def _compute_summary(self):
        labels = dict(self._fields['format']._description_selection(self.env))
        for design in self:
            parts = [labels.get(design.format, '')]
            if design.format == 'poster':
                parts[0] = '%s %s' % (parts[0], (design.paper or 'a4').upper())
            if design.format == 'carousel':
                parts.append(_('%s slides', len(design.slide_ids)))
            parts.append(design.plan_id.name or _('no campaign'))
            design.summary = ' · '.join(parts)

    def _active(self):
        """The slide being edited: the chosen one while it is still a slide of this design, else the first."""
        self.ensure_one()
        slides = self.slide_ids
        chosen = self.active_slide_id
        for slide in slides:
            if chosen and (slide._origin or slide) == (chosen._origin or chosen):
                return slide
        return slides[:1]

    def _position(self, slide):
        slides = [(s._origin or s) for s in self.slide_ids]
        target = slide._origin or slide
        return slides.index(target) if target in slides else 0

    @api.depends('active_slide_id', 'slide_ids', 'format')
    def _compute_slide_label(self):
        for design in self:
            slide = design._active()
            count = len(design.slide_ids)
            if not slide or design.format != 'carousel':
                design.slide_label = _('Text and picture')
                design.preview_label = ''
                continue
            position = design._position(slide)
            design.slide_label = _('Slide %s', slide._label_at(position, count))
            design.preview_label = _('Slide %(n)s of %(count)s', n=position + 1, count=count)

    def _spec(self, slide, **values):
        """What the renderer draws for ``slide``; ``values`` replace the saved texts (the form, not saved yet)."""
        self.ensure_one()
        spec = dict(self.brand_id._kit() if self.brand_id else {})
        spec.update(size=render.size_of(self.format or 'square', self.paper or 'a4'),
                    template=self.template_id.code, look=slide.look or 'main',
                    headline=slide.headline, text=slide.text, button=slide.button, image=raw(slide.image),
                    index=self._position(slide), count=len(self.slide_ids) or 1)
        spec.update(values)
        return spec

    @api.depends('active_slide_id', 'slide_ids', 'slide_headline', 'slide_text', 'slide_button', 'slide_image',
                 'slide_look', 'template_id', 'format', 'paper', 'brand_id')
    def _compute_preview(self):
        for design in self:
            slide = design._active()
            if not slide or not design.template_id:
                design.preview = False
                continue
            # The form's values of the slide being edited, so the preview follows what is typed.
            spec = design._spec(slide, headline=design.slide_headline, text=design.slide_text,
                                button=design.slide_button, image=raw(design.slide_image),
                                look=design.slide_look or 'main')
            design.preview = BinaryBytes(render.png(render.render(spec, PREVIEW_WIDTH)))

    @api.depends('slide_ids', 'template_id', 'format', 'paper', 'brand_id')
    def _compute_thumbnail(self):
        for design in self:
            slide = design.slide_ids[:1]
            design.thumbnail = BinaryBytes(render.png(render.render(design._spec(slide), 360))) \
                if slide and design.template_id else False

    @api.depends('slide_ids', 'active_slide_id')
    def _compute_strip(self):
        for design in self:
            if design.format != 'carousel' or not design.id:
                design.strip = False
                continue
            active = design._active()
            stamp = fields.Datetime.now().strftime('%H%M%S%f')
            pictures = []
            for slide in design.slide_ids.filtered('id'):
                pictures.append(
                    Markup('<img src="/web/image/mi.design.slide/%s/preview?unique=%s" alt="%s" class="%s"/>') % (
                        slide.id, stamp, _('Slide %s', slide.label),
                        'o_mi_design_thumb o_selected' if slide == active else 'o_mi_design_thumb'))
            design.strip = Markup('').join(pictures)

    @api.depends('format')
    def _compute_use_targets(self):
        for design in self:
            targets = []
            if 'omni.social.publication' in self.env and design.format != 'email_header' \
                    and self.env['omni.social.publication'].has_access('create'):
                targets.append('social')
            if design.format == 'email_header' and 'mailing.mailing' in self.env \
                    and self.env['mailing.mailing'].has_access('create'):
                targets.append('email')
            if 'mi.proof' in self.env and self.env['mi.proof'].has_access('create'):
                targets.append('proof')
            design.use_targets = ','.join(targets)

    # ------------------------------------------------------------------ slides

    @api.constrains('slide_ids', 'format')
    def _check_slides(self):
        for design in self:
            count = len(design.slide_ids)
            if design.format == 'carousel' and not render.CAROUSEL_MIN <= count <= render.CAROUSEL_MAX:
                raise ValidationError(_('A carousel has %(min)s to %(max)s slides.', min=render.CAROUSEL_MIN,
                                        max=render.CAROUSEL_MAX))
            if design.format != 'carousel' and count != 1:
                raise ValidationError(_('Only a carousel has several slides.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('slide_ids'):
                count = 3 if vals.get('format') == 'carousel' else 1
                vals['slide_ids'] = [Command.create({'sequence': index * 10}) for index in range(count)]
        designs = super().create(vals_list)
        for design in designs:
            if not design.active_slide_id:
                design.active_slide_id = design.slide_ids[:1]
        return designs

    def write(self, vals):
        result = super().write(vals)
        for design in self:
            if design.active_slide_id not in design.slide_ids:
                design.active_slide_id = design.slide_ids[:1]
        return result

    def action_add_slide(self):
        """A new slide before the closing one, ready to edit."""
        self.ensure_one()
        if self.format != 'carousel':
            raise UserError(_('Only a carousel has several slides.'))
        if len(self.slide_ids) >= render.CAROUSEL_MAX:
            raise UserError(_('A carousel has at most %s slides.', render.CAROUSEL_MAX))
        slides = self.slide_ids
        last = slides[-1:]
        for index, slide in enumerate(slides - last):
            slide.sequence = index * 10
        new = self.env['mi.design.slide'].create({'design_id': self.id, 'sequence': len(slides) * 10 - 10,
                                                  'look': last.look or 'main'})
        last.sequence = len(slides) * 10
        self.active_slide_id = new
        return True

    # ------------------------------------------------------------------ export (board 13.3)

    def _images(self, out_width=None):
        self.ensure_one()
        self.check_access('read')
        return [render.render(self._spec(slide), out_width) for slide in self.slide_ids]

    def _file_name(self):
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\- ]+', '', self.name or '')).strip()[:60] or 'design'

    def _export(self, kind):
        """(file name, content type, bytes): a PNG (a zip of one PNG per slide for a carousel) or a PDF."""
        self.ensure_one()
        images = self._images()
        name = self._file_name()
        if kind == 'pdf':
            return name + '.pdf', 'application/pdf', render.pdf(images, 300 if self.format == 'poster' else 150)
        if len(images) == 1:
            return name + '.png', 'image/png', render.png(images[0])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
            for index, image in enumerate(images, start=1):
                archive.writestr('%s-%02d.png' % (name, index), render.png(image))
        return name + '.zip', 'application/zip', buffer.getvalue()

    def action_download_png(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/marketing_intel_design/%s/png' % self.id, 'target': 'download'}

    def action_download_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/marketing_intel_design/%s/pdf' % self.id, 'target': 'download'}

    def action_copy_format(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.design.copy', 'view_mode': 'form',
                'target': 'new', 'name': _('Copy to another format'),
                'context': {'default_design_id': self.id}}

    def action_open_brand_kit(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.brand', 'res_id': self.brand_id.id,
                'view_mode': 'form', 'views': [(False, 'form')]}

    # ------------------------------------------------------------------ pictures (board 13.3, 13.4)

    def action_pick_library(self):
        """From the library: the photos of the team's social posts."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'omni.social.media', 'name': _('From the library'),
                'view_mode': 'kanban', 'target': 'new', 'domain': [('kind', '=', 'image')],
                'views': [(self.env.ref('marketing_intel_design.media_picker_kanban').id, 'kanban')],
                'context': {'mi_slide_id': self._active().id}}

    def action_ai_image(self):
        self.ensure_one()
        slide = self._active()
        Ask = self.env['mi.design.image.ask']
        ask = Ask.search([('slide_id', '=', slide.id), ('user_id', '=', self.env.uid)], limit=1) \
            or Ask.create({'slide_id': slide.id})
        return ask._open()

    # ------------------------------------------------------------------ ✦ Suggest text for all slides

    def _agent(self):
        return self.env['mi.research']._agent(self.brand_id)

    def _suggest_prompt(self):
        self.ensure_one()
        brand, plan = self.brand_id, self.plan_id
        count = len(self.slide_ids)
        lines = [
            'You write the texts of a designed %s for a marketing team.' % dict(FORMATS)[self.format].lower(),
            'Brand: %s. What it sells: %s. Audience: %s. Voice: %s.' % (
                brand.name, brand.offering or '-', brand.audience or '-', brand.tone or '-'),
        ]
        if plan:
            lines.append('Campaign: %s. Key message: %s. For: %s.' % (plan.name, plan.message or '-',
                                                                     plan.audience or '-'))
        lines.append('The design is called "%s" and uses the "%s" template.' % (self.name, self.template_id.name))
        if count > 1:
            lines.append('It has %s slides: slide 1 is the cover, slide %s closes with a call to action, the '
                         'slides between carry one point each.' % (count, count))
        lines.append('Texts already written (keep their meaning, improve the wording only if needed):')
        for index, slide in enumerate(self.slide_ids, start=1):
            lines.append('Slide %s: headline "%s"; text "%s"; button "%s"' % (
                index, slide.headline or '', slide.text or '', slide.button or ''))
        lines += [
            ('Reply with JSON only, no other words: a list with one object per slide, in order, each with the keys '
             '"headline" (at most %(headline)s characters), "text" (at most %(text)s characters) and "button" (at '
             'most %(button)s characters, or an empty string where no button fits).' % LIMITS),
            ('Do not invent prices, dates, numbers or promises. Write in the language of the texts above, or of the '
             'campaign when they are empty.'),
        ]
        return '\n'.join(lines)

    def action_suggest_text(self):
        self.ensure_one()
        agent = self._agent()
        if not agent:
            raise UserError(self.env['mi.design.image.ask']._no_assistant_text())
        try:
            run = self.env['ai.agent.run']._ask(agent, self._suggest_prompt(), caller='marketing', origin=self)
        except (UserError, AccessError) as error:
            self.write({'suggest_state': 'failed', 'suggest_error': str(error.args[0] if error.args else error)})
            return True
        self.write({'suggest_state': 'asking', 'suggest_error': False, 'suggest_run_id': run.id,
                    'suggest_asked_at': fields.Datetime.now()})
        return True

    @api.model
    def _parse_suggestions(self, answer):
        """The assistant's reply as a list of {headline, text, button}; [] when it is not the JSON asked for."""
        match = re.search(r'\[.*\]', answer or '', re.S)
        try:
            rows = json.loads(match.group(0)) if match else []
        except ValueError:
            return []
        clean = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                return []
            clean.append({name: str(row.get(name) or '').strip()[:LIMITS[name]] for name in LIMITS})
        return clean

    def _ai_agent_finished(self, ai_run):
        self.ensure_one()
        if ai_run.id != self.suggest_run_id.id or self.suggest_state != 'asking':
            return
        rows = self._parse_suggestions(ai_run.answer) if ai_run.state == 'completed' else []
        if not rows:
            reason = ai_run._reason_for_people()['text'] if ai_run.state != 'completed' \
                else _('The assistant did not give texts for the slides. Try again.')
            self.write({'suggest_state': 'failed', 'suggest_error': reason})
            return
        # Empty fields are filled; a field with text keeps it and gets the suggestion beside it (Use / Discard).
        for slide, row in zip(self.slide_ids, rows):
            values = {}
            for name in LIMITS:
                if not row[name]:
                    continue
                if not slide[name]:
                    values[name] = row[name]
                elif slide[name].strip() != row[name]:
                    values['suggested_' + name] = row[name]
            slide.write(values)
        self.write({'suggest_state': False, 'suggest_error': False})

    def action_dismiss_suggest_error(self):
        self.write({'suggest_state': False, 'suggest_error': False})
        return True

    def _suggestion(self, name, use):
        self.ensure_one()
        if name not in LIMITS:
            raise UserError(_('Unknown text.'))
        slide = self._active()
        values = {'suggested_' + name: False}
        if use and slide['suggested_' + name]:
            values[name] = slide['suggested_' + name]
        slide.write(values)
        return True

    def action_use_headline(self):
        return self._suggestion('headline', True)

    def action_discard_headline(self):
        return self._suggestion('headline', False)

    def action_use_text(self):
        return self._suggestion('text', True)

    def action_discard_text(self):
        return self._suggestion('text', False)

    def action_use_button(self):
        return self._suggestion('button', True)

    def action_discard_button(self):
        return self._suggestion('button', False)


class DesignSlide(models.Model):
    _name = 'mi.design.slide'
    _description = 'Design slide'
    _order = 'sequence, id'

    design_id = fields.Many2one('mi.design', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='design_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    label = fields.Char(compute='_compute_label', string='Slide')
    headline = fields.Char(size=LIMITS['headline'])
    text = fields.Text()
    button = fields.Char(string='Button text', size=LIMITS['button'])
    image = fields.Image(string='Picture', max_width=1920, max_height=1920)
    has_image = fields.Boolean(compute='_compute_has_image', string='Has a picture')
    look = fields.Selection(LOOKS, string='Colours', default='main', required=True)
    suggested_headline = fields.Char(readonly=True, copy=False)
    suggested_text = fields.Text(readonly=True, copy=False)
    suggested_button = fields.Char(readonly=True, copy=False)
    preview = fields.Image(compute='_compute_preview')

    @api.constrains('text')
    def _check_text(self):
        for slide in self:
            if slide.text and len(slide.text) > LIMITS['text']:
                raise ValidationError(_('The text of a slide has at most %s characters.', LIMITS['text']))

    @api.model
    def _label_at(self, position, count):
        if position == 0:
            return _('Cover')
        if position == count - 1:
            return _('Last')
        return str(position)

    @api.depends('design_id.slide_ids', 'design_id.slide_ids.sequence')
    def _compute_label(self):
        for slide in self:
            design = slide.design_id
            slide.label = self._label_at(design._position(slide), len(design.slide_ids)) if design else ''

    @api.depends('image')
    def _compute_has_image(self):
        for slide in self:
            slide.has_image = bool(slide.image)

    @api.depends('headline', 'text', 'button', 'image', 'look', 'design_id.template_id', 'design_id.format')
    def _compute_preview(self):
        for slide in self:
            design = slide.design_id
            slide.preview = BinaryBytes(render.png(render.render(design._spec(slide), 160))) \
                if design.template_id else False

    def _touch(self, designs):
        designs = designs.exists()
        designs.write({'touched_at': fields.Datetime.now()})
        designs.invalidate_recordset(['slide_ids'])  # their order may have changed

    @api.model_create_multi
    def create(self, vals_list):
        slides = super().create(vals_list)
        self._touch(slides.design_id)
        return slides

    def write(self, vals):
        result = super().write(vals)
        self._touch(self.design_id)
        return result

    def unlink(self):
        designs = self.design_id
        result = super().unlink()
        self._touch(designs)
        return result

    def _set_picture(self, content):
        """Put a picture (bytes) on the slide, after checking the person may change the design."""
        self.ensure_one()
        self.design_id.check_access('write')
        self.image = BinaryBytes(content)
