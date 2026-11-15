"""Draws a design: one picture per slide, from a template, the brand kit and the person's texts.

Drawn with Pillow and the fonts Odoo ships (``web/static/fonts``), so the preview, the PNG and the PDF are the same
picture and no HTML-to-image program is needed on the server. A template is a set of switches for one layout that
adapts to the format's size; texts shrink to fit their area and are cut with "…" only past the smallest size.
"""

import io
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps

from odoo.tools.misc import file_path

# key: (label, bold file, regular file), under web/static/fonts
FONTS = {
    'montserrat': ('Montserrat', 'google/Montserrat/Montserrat-Bold.ttf', 'google/Montserrat/Montserrat-Regular.ttf'),
    'open_sans': ('Open Sans', 'google/Open_Sans/Open_Sans-Bold.ttf', 'google/Open_Sans/Open_Sans-Regular.ttf'),
    'raleway': ('Raleway', 'google/Raleway/Raleway-Bold.ttf', 'google/Raleway/Raleway-Regular.ttf'),
    'oswald': ('Oswald', 'google/Oswald/Oswald-Bold.ttf', 'google/Oswald/Oswald-Regular.ttf'),
    'roboto': ('Roboto', 'google/Roboto/Roboto-Bold.ttf', 'google/Roboto/Roboto-Regular.ttf'),
    'lato': ('Lato', 'lato/Lato-Bol-webfont.ttf', 'lato/Lato-Reg-webfont.ttf'),
}
# format: (label, width, height) in pixels; posters are A4 or A3 at 300 dpi (see ``size_of``)
FORMATS = {
    'square': ('Square post', 1080, 1080),
    'portrait': ('Portrait post', 1080, 1350),
    'story': ('Story', 1080, 1920),
    'carousel': ('Carousel', 1080, 1350),
    'poster': ('Poster', 2480, 3508),
    'email_header': ('Email header', 1200, 400),
}
PAPERS = {'a4': (2480, 3508), 'a3': (3508, 4961)}
# What each template draws. picture: 'big' always keeps a picture area, 'top' only when a picture is chosen.
TEMPLATES = {
    'offer': {'button': True, 'picture': 'top'},
    'announcement': {'bar': True, 'picture': 'top'},
    'quote': {'quote': True},
    'photo': {'picture': 'big'},
    'event': {'button': True, 'boxed': True, 'picture': 'top'},
    'tips': {'number': True, 'button': 'last', 'picture': 'top'},
}
# Odoo's own colours, used while the brand kit is empty.
DEFAULT_COLORS = {'main': '#71639e', 'accent': '#017e84', 'dark': '#212529', 'light': '#f8f9fa'}
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10


def size_of(fmt, paper='a4'):
    if fmt == 'poster':
        return PAPERS.get(paper, PAPERS['a4'])
    return FORMATS[fmt][1:]


def is_hex(value):
    return bool(value and HEX.match(value))


def _rgb(value, fallback):
    value = value if is_hex(value) else fallback
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _is_dark(rgb):
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255 < 0.6


@lru_cache(maxsize=256)
def _font(key, bold, size):
    files = FONTS.get(key) or FONTS['montserrat']
    return ImageFont.truetype(file_path('web/static/fonts/' + files[1 if bold else 2]), max(int(size), 6))


def _wrap(text, font, width):
    lines = []
    for paragraph in (text or '').splitlines() or ['']:
        line = ''
        for word in paragraph.split():
            trial = (line + ' ' + word).strip()
            if line and font.getlength(trial) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def _fit(text, key, bold, largest, smallest, width, height, spacing=1.18):
    """The biggest size at which ``text`` fits (font, lines, line height); past the smallest it is cut with "…"."""
    size = largest
    while True:
        font = _font(key, bold, size)
        lines = _wrap(text, font, width)
        line_height = size * spacing
        fits = len(lines) * line_height <= height and all(font.getlength(line) <= width for line in lines)
        if fits or size <= smallest:
            break
        size = max(smallest, size - max(1, round(size * 0.06)))
    if not fits:
        keep = max(1, int(height // line_height))
        if len(lines) > keep:
            lines = lines[:keep]
            lines[-1] = lines[-1].rstrip('.,;: ') + '…'
        for index, line in enumerate(lines):
            while len(line) > 1 and font.getlength(line) > width:
                line = line[:-2].rstrip() + '…'
            lines[index] = line
    return font, lines, line_height


def _open(data):
    """A picture the person uploaded, or None when it cannot be read."""
    if not data:
        return None
    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
        return ImageOps.exif_transpose(picture)
    except Exception:  # noqa: BLE001 - an unreadable picture is left out of the design
        return None


def render(spec, out_width=None):
    """The slide described by ``spec`` as an RGB image.

    spec: size (w, h), template, look ('main' / 'light' / 'dark'), colors {main, accent, dark, light}, fonts
    (heading key, text key), headline, text, button, image, logo, logo_dark (bytes or None), brand, website, handle,
    footer, index, count. ``out_width`` scales the whole picture (the preview is drawn smaller than the export).
    """
    width, height = spec['size']
    scale = (out_width / width) if out_width else 1
    W, H = max(round(width * scale), 8), max(round(height * scale), 8)
    unit = math.sqrt(W * H) / 1080
    options = TEMPLATES.get(spec.get('template')) or TEMPLATES['announcement']
    colors = {name: _rgb((spec.get('colors') or {}).get(name), DEFAULT_COLORS[name]) for name in DEFAULT_COLORS}
    look = spec.get('look') or 'main'
    background = colors[look if look in ('main', 'light', 'dark') else 'main']
    on_dark = _is_dark(background)
    ink = (255, 255, 255) if on_dark else colors['dark']
    if not on_dark and not _is_dark(ink):
        ink = (33, 37, 41)
    accent = colors['accent'] if colors['accent'] != background else colors['main']
    if accent == background:
        accent = ink
    heading_font, text_font = spec.get('fonts') or ('montserrat', 'open_sans')
    index, count = spec.get('index') or 0, spec.get('count') or 1
    headline, text, button = (spec.get(name) or '' for name in ('headline', 'text', 'button'))

    image = Image.new('RGB', (W, H), background)
    draw = ImageDraw.Draw(image)
    pad = round(70 * unit)
    left, top, right, bottom = pad, pad, W - pad, H - pad
    wide = W / H > 2

    # The picture area
    picture = _open(spec.get('image'))
    mode = options.get('picture')
    if mode == 'big' or (mode == 'top' and picture):
        if wide:
            box = (round(W * 0.62), 0, W, H)
            right = box[0] - pad
        else:
            box = (0, 0, W, round(H * (0.56 if mode == 'big' else 0.42)))
            top = box[3] + round(pad * 0.7)
        size = (box[2] - box[0], box[3] - box[1])
        if picture:
            image.paste(ImageOps.fit(picture.convert('RGB'), size, Image.LANCZOS), box[:2])
        else:
            mix = tuple((a * 3 + b) // 4 for a, b in zip(background, ink))
            draw.rectangle(box, fill=mix)

    # The brand line at the bottom: the logo (or the name) left, the handle or website right
    mark_height = round(46 * unit)
    logo = _open(spec.get('logo_dark') if on_dark else spec.get('logo')) \
        or _open(spec.get('logo') if on_dark else spec.get('logo_dark'))
    line_y = bottom - mark_height
    if logo:
        ratio = min(mark_height / logo.height, (right - left) * 0.4 / logo.width)
        logo = logo.convert('RGBA').resize((max(round(logo.width * ratio), 1), max(round(logo.height * ratio), 1)),
                                           Image.LANCZOS)
        image.paste(logo, (left, line_y + (mark_height - logo.height) // 2), logo)
    elif spec.get('brand'):
        font = _font(heading_font, True, 30 * unit)
        draw.text((left, line_y + mark_height / 2), spec['brand'], font=font, fill=ink, anchor='lm')
    contact = spec.get('handle') or spec.get('website') or ''
    if spec.get('handle') and spec.get('website') and not wide and spec['size'][0] >= 2000:
        contact = '%s · %s' % (spec['website'], spec['handle'])
    if contact:
        font = _font(text_font, False, 26 * unit)
        draw.text((right, line_y + mark_height / 2), contact, font=font, fill=ink, anchor='rm')
    bottom = line_y - round(30 * unit)
    if spec.get('footer') and spec['size'][0] >= 2000:  # posters carry the brand's footer line
        font = _font(text_font, False, 24 * unit)
        draw.text((left, bottom), spec['footer'], font=font, fill=ink, anchor='ls')
        bottom -= round(50 * unit)

    # The button keeps its place at the bottom of the text area
    show_button = button and (options.get('button') is True or (options.get('button') == 'last' and count > 1
                                                                and index == count - 1))
    if show_button:
        font, lines, _line = _fit(button, heading_font, True, 32 * unit, 20 * unit, right - left - 80 * unit,
                                  44 * unit)
        label = lines[0] if lines else ''
        button_height = round(78 * unit)
        button_width = min(round(font.getlength(label) + 80 * unit), right - left)
        box = (left, bottom - button_height, left + button_width, bottom)
        draw.rounded_rectangle(box, radius=round(10 * unit), fill=accent)
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label, font=font, anchor='mm',
                  fill=(255, 255, 255) if _is_dark(accent) else (33, 37, 41))
        bottom = box[1] - round(34 * unit)

    y = top
    if options.get('number') and count > 1 and 0 < index < count - 1:
        font = _font(heading_font, True, min(150 * unit, (bottom - y) * 0.3))
        draw.text((left, y), str(index), font=font, fill=accent, anchor='la')
        y += round(font.size * 1.1)
    if options.get('bar'):
        draw.rectangle((left, y, left + round(96 * unit), y + round(10 * unit)), fill=accent)
        y += round(40 * unit)
    if options.get('quote'):
        font = _font(heading_font, True, min(220 * unit, (bottom - y) * 0.35))
        draw.text((left, y - font.size * 0.15), '“', font=font, fill=accent, anchor='la')
        y += round(font.size * 0.62)

    room = max(bottom - y, 10)
    if headline:
        share = 0.62 if text else 1
        largest = (112 if count > 1 and index == 0 else 92) * unit
        font, lines, line_height = _fit(headline, heading_font, True, largest, 30 * unit, right - left,
                                        room * share, 1.14)
        for line in lines:
            draw.text((left, y), line, font=font, fill=ink, anchor='la')
            y += line_height
        y += round(22 * unit)
    if text and bottom - y > 20 * unit:
        inset = round(26 * unit) if options.get('boxed') else 0
        font, lines, line_height = _fit(text, text_font, False, 42 * unit, 22 * unit, right - left - 2 * inset,
                                        bottom - y - 2 * inset, 1.4)
        if inset:
            box_height = round(len(lines) * line_height + 2 * inset)
            draw.rounded_rectangle((left, y, right, y + box_height), radius=round(10 * unit), outline=accent,
                                   width=max(round(4 * unit), 1))
            y += inset
        for line in lines:
            draw.text((left + inset, y), line, font=font, fill=ink, anchor='la')
            y += line_height
    return image


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def pdf(images, dpi=150):
    buffer = io.BytesIO()
    images[0].save(buffer, 'PDF', save_all=True, append_images=images[1:], resolution=dpi)
    return buffer.getvalue()
