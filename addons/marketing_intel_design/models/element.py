"""The elements of a free design (plan M9, boards 16.1 to 16.3): text, shapes, pictures and the logo, each with a
place and a size in the format's pixels. Drawn back to front in ``sequence`` order; the Layers list shows the
reverse (the top layer first). Colours are the brand kit's four, never free hex values.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import BinaryBytes

from .brand import raw

KINDS = [('text', 'Text'), ('shape', 'Shape'), ('picture', 'Picture'), ('logo', 'Logo')]
COLORS = [('main', 'Main'), ('accent', 'Accent'), ('dark', 'Dark'), ('light', 'Light')]
SHAPES = [('rect', 'Rectangle'), ('round', 'Rounded'), ('ellipse', 'Ellipse')]
ALIGNS = [('left', 'Left'), ('center', 'Centre'), ('right', 'Right')]
TEXT_LIMIT = 600
MIN_SIDE, MAX_SIDE = 2, 8000


class DesignElement(models.Model):
    _name = 'mi.design.element'
    _description = 'Element of a free design'
    _order = 'sequence, id'

    design_id = fields.Many2one('mi.design', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='design_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection(KINDS, required=True, default='text')
    name = fields.Char(compute='_compute_name', string='Layer')
    x = fields.Integer(default=0)
    y = fields.Integer(default=0)
    w = fields.Integer(string='Width', default=400)
    h = fields.Integer(string='Height', default=120)
    text = fields.Text()
    font = fields.Selection([('heading', 'Headings'), ('text', 'Text')], default='text', required=True)
    bold = fields.Boolean()
    size = fields.Integer(default=48)
    color = fields.Selection(COLORS, default='dark', required=True)
    align = fields.Selection(ALIGNS, default='left', required=True)
    shape = fields.Selection(SHAPES, default='rect', required=True)
    image = fields.Image(max_width=1920, max_height=1920)
    hidden = fields.Boolean()
    locked = fields.Boolean()

    @api.depends('kind', 'text', 'shape')
    def _compute_name(self):
        labels = dict(self._fields['kind']._description_selection(self.env))
        shapes = dict(self._fields['shape']._description_selection(self.env))
        for element in self:
            if element.kind == 'text':
                first = (element.text or '').strip().splitlines()[:1]
                element.name = (first[0][:24] + ('…' if len(first[0]) > 24 else '')) if first else labels['text']
            elif element.kind == 'shape':
                element.name = shapes[element.shape]
            else:
                element.name = labels[element.kind]

    @api.constrains('x', 'y', 'w', 'h', 'size', 'text')
    def _check_values(self):
        for element in self:
            if not MIN_SIDE <= element.w <= MAX_SIDE or not MIN_SIDE <= element.h <= MAX_SIDE:
                raise ValidationError(_('An element is between %(min)s and %(max)s pixels wide and high.',
                                        min=MIN_SIDE, max=MAX_SIDE))
            if element.kind == 'text' and not 6 <= element.size <= 800:
                raise ValidationError(_('Text is between 6 and 800 pixels high.'))
            if element.text and len(element.text) > TEXT_LIMIT:
                raise ValidationError(_('A text has at most %s characters.', TEXT_LIMIT))

    @api.model_create_multi
    def create(self, vals_list):
        elements = super().create(vals_list)
        elements.design_id._touch()
        return elements

    def write(self, vals):
        designs = self.design_id
        result = super().write(vals)
        (designs | self.design_id)._touch()
        return result

    def unlink(self):
        designs = self.design_id
        result = super().unlink()
        designs._touch()
        return result

    def _spec(self):
        """What the renderer needs of this element."""
        self.ensure_one()
        return {'kind': self.kind, 'x': self.x, 'y': self.y, 'w': self.w, 'h': self.h, 'text': self.text,
                'font': self.font, 'bold': self.bold, 'size': self.size, 'color': self.color, 'align': self.align,
                'shape': self.shape, 'image': raw(self.image), 'hidden': self.hidden}

    def _set_picture(self, content):
        """Put a picture (bytes) on a picture element, after checking the person may change the design."""
        self.ensure_one()
        self.design_id.check_access('write')
        self.image = BinaryBytes(content)

    @api.model
    def _from_render(self, collected, design):
        """Element values from what the renderer drew for a template design (``render.render(..., collect=)``)."""
        values = []
        for index, item in enumerate(collected, start=1):
            vals = {key: item[key] for key in ('kind', 'x', 'y', 'w', 'h', 'text', 'font', 'bold', 'size', 'color',
                                               'align', 'shape') if key in item}
            if item.get('image'):
                vals['image'] = BinaryBytes(item['image'])
            vals.update(design_id=design.id, sequence=index * 10)
            values.append(vals)
        return values

    def _scaled(self, ratio_x, ratio_y):
        """The values of this element in a format ratio_x times as wide and ratio_y times as high."""
        self.ensure_one()
        ratio = min(ratio_x, ratio_y)
        values = {'x': round(self.x * ratio_x), 'y': round(self.y * ratio_y),
                  'w': max(round(self.w * ratio_x), MIN_SIDE), 'h': max(round(self.h * ratio_y), MIN_SIDE)}
        if self.kind == 'text':
            values['size'] = max(round(self.size * ratio), 6)
        return values


def element_specs(design):
    """The elements of ``design``, back to front, as the renderer takes them."""
    return [element._spec() for element in design.element_ids]

