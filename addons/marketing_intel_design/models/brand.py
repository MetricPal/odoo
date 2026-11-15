from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import BinaryBytes

from . import render

FONT_CHOICES = [(key, values[0]) for key, values in render.FONTS.items()]
KIT_COLORS = ('kit_color_main', 'kit_color_accent', 'kit_color_dark', 'kit_color_light')


def raw(value):
    """The bytes of a Binary / Image field value (Odoo 20 returns BinaryValue objects)."""
    if not value:
        return None
    return value.content if hasattr(value, 'content') else value


class Brand(models.Model):
    """The brand kit (plan M6, approved board 13.1): what every design of the brand is drawn with."""
    _inherit = 'mi.brand'

    kit_logo = fields.Image(string='Logo', max_width=1024, max_height=1024)
    kit_logo_dark = fields.Image(string='Logo on dark', max_width=1024, max_height=1024)
    kit_icon = fields.Image(string='Icon (square)', max_width=512, max_height=512)
    kit_color_main = fields.Char(string='Main colour')
    kit_color_accent = fields.Char(string='Accent colour')
    kit_color_dark = fields.Char(string='Dark')
    kit_color_light = fields.Char(string='Light')
    kit_font_heading = fields.Selection(FONT_CHOICES, string='Headings', default='montserrat', required=True)
    kit_font_text = fields.Selection(FONT_CHOICES, string='Text', default='open_sans', required=True)
    kit_website = fields.Char(string='Website')
    kit_handle = fields.Char(string='Social handle')
    kit_footer = fields.Char(string='Footer line')
    kit_empty = fields.Boolean(compute='_compute_kit_empty')
    kit_preview_main = fields.Image(compute='_compute_kit_preview', string='On the main colour')
    kit_preview_light = fields.Image(compute='_compute_kit_preview', string='On the light colour')

    @api.constrains(*KIT_COLORS)
    def _check_kit_colors(self):
        for brand in self:
            for name in KIT_COLORS:
                if brand[name] and not render.is_hex(brand[name]):
                    raise ValidationError(_('Choose "%s" with the colour picker (a colour like #0B5FA5).',
                                            brand._fields[name].string))

    @api.depends('kit_logo', 'kit_logo_dark', 'kit_icon', *KIT_COLORS)
    def _compute_kit_empty(self):
        for brand in self:
            brand.kit_empty = not (brand.kit_logo or brand.kit_logo_dark or brand.kit_icon
                                   or any(brand[name] for name in KIT_COLORS))

    def _kit(self):
        """What the renderer needs from the brand. An empty kit draws with the company logo and Odoo's colours."""
        self.ensure_one()
        brand = self.sudo()  # sudo: mi.brand, res.company - the kit and the company logo of a brand the person reads
        logo = raw(brand.kit_logo) or raw(brand.kit_icon)
        logo_dark = raw(brand.kit_logo_dark)
        if brand.kit_empty:
            logo = raw(brand.company_id.logo)
        return {
            'colors': {'main': brand.kit_color_main, 'accent': brand.kit_color_accent,
                       'dark': brand.kit_color_dark, 'light': brand.kit_color_light},
            'fonts': (brand.kit_font_heading or 'montserrat', brand.kit_font_text or 'open_sans'),
            'logo': logo, 'logo_dark': logo_dark, 'brand': brand.name,
            'website': brand.kit_website, 'handle': brand.kit_handle, 'footer': brand.kit_footer,
        }

    @api.depends('name', 'kit_logo', 'kit_logo_dark', 'kit_icon', 'kit_font_heading', 'kit_font_text', 'kit_website',
                 'kit_handle', 'kit_footer', *KIT_COLORS)
    def _compute_kit_preview(self):
        for brand in self:
            kit = brand._kit()
            sample = dict(kit, size=(1080, 1080), template='offer', headline=_('Headline in the heading font'),
                          text=_('A line of text in the text font.'), button=_('Button'))
            brand.kit_preview_main = BinaryBytes(render.png(render.render(dict(sample, look='main'), 420)))
            brand.kit_preview_light = BinaryBytes(render.png(render.render(
                dict(sample, look='light', template='announcement', headline=_('The same on the light colour'),
                     text=''), 420)))
