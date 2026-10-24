"""Small dependency-free charts: SVG for the board, HTML and PDF; PNG (Pillow) for Word.

Charts are drawn on the server so that the board, the HTML file and the PDF
show exactly the same picture. PowerPoint and Excel use their own native charts.
"""

import io
import math

from markupsafe import Markup, escape

PALETTE = ['#2A9D8F', '#E76F51', '#F4A261', '#264653', '#8AB17D', '#E9C46A', '#6D597A', '#B56576',
           '#457B9D', '#A8DADC', '#F28482', '#84A59D']
KINDS = [('bar', 'Bar'), ('hbar', 'Horizontal bar'), ('line', 'Line'), ('pie', 'Pie'), ('donut', 'Donut')]


def colors(accent, count):
    return [accent] + PALETTE[:max(count - 1, 0)] if count else []


def _fmt(value):
    if isinstance(value, float) and not value.is_integer():
        return f'{value:,.1f}'
    return f'{int(value):,}'


def _short(label, size=14):
    label = str(label)
    return label if len(label) <= size else label[:size - 1] + '…'


def svg(kind, labels, values, accent='#714B67', width=600, height=300):
    """An inline SVG chart (viewBox based, scales to its box)."""
    if not labels:
        return Markup('<div class="o_rs_empty">No data</div>')
    values = [float(v or 0) for v in values]
    parts = [f'<svg class="o_rs_chart" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'preserveAspectRatio="xMidYMid meet" font-family="sans-serif" font-size="11">']
    if kind in ('pie', 'donut'):
        parts += _pie(labels, values, accent, width, height, kind == 'donut')
    elif kind == 'hbar':
        parts += _hbar(labels, values, accent, width, height)
    else:
        parts += _bars_or_line(kind, labels, values, accent, width, height)
    parts.append('</svg>')
    return Markup(''.join(parts))


def _axis_max(values):
    top = max(values + [0])
    if top <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(top))
    for step in (1, 2, 2.5, 5, 10):
        if top <= step * magnitude:
            return step * magnitude
    return top


def _bars_or_line(kind, labels, values, accent, width, height):
    left, right, top, bottom = 48, 12, 14, 44
    plot_w, plot_h = width - left - right, height - top - bottom
    vmax = _axis_max(values)
    out = []
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e5e5e5"/>')
        out.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#777">{_fmt(vmax * i / 4)}</text>')
    step = plot_w / len(values)
    points = []
    for i, (label, value) in enumerate(zip(labels, values)):
        x = left + step * i
        h = plot_h * value / vmax if vmax else 0
        if kind == 'line':
            points.append((x + step / 2, top + plot_h - h))
        else:
            bar = max(step * 0.7, 2)
            out.append(f'<rect x="{x + (step - bar) / 2:.1f}" y="{top + plot_h - h:.1f}" width="{bar:.1f}" '
                       f'height="{h:.1f}" rx="2" fill="{accent}"><title>{escape(label)}: {_fmt(value)}</title></rect>')
        if len(values) <= 12 or i % math.ceil(len(values) / 12) == 0:
            out.append(f'<text x="{x + step / 2:.1f}" y="{height - bottom + 16}" text-anchor="middle" fill="#555">'
                       f'{escape(_short(label, max(int(step / 6), 4)))}</text>')
    if points:
        path = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
        out.append(f'<polyline points="{path}" fill="none" stroke="{accent}" stroke-width="2.5"/>')
        out += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{accent}"/>' for x, y in points]
    return out


def _hbar(labels, values, accent, width, height):
    left, right, top = 120, 48, 8
    rows = len(values)
    row_h = (height - top * 2) / rows
    vmax = _axis_max(values)
    out = []
    for i, (label, value) in enumerate(zip(labels, values)):
        y = top + row_h * i
        w = (width - left - right) * value / vmax if vmax else 0
        bar = max(row_h * 0.7, 2)
        out.append(f'<text x="{left - 6}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end" fill="#555">'
                   f'{escape(_short(label, 18))}</text>')
        out.append(f'<rect x="{left}" y="{y + (row_h - bar) / 2:.1f}" width="{w:.1f}" height="{bar:.1f}" rx="2" '
                   f'fill="{accent}"/>')
        out.append(f'<text x="{left + w + 4:.1f}" y="{y + row_h / 2 + 4:.1f}" fill="#333">{_fmt(value)}</text>')
    return out


def _pie(labels, values, accent, width, height, donut):
    total = sum(v for v in values if v > 0) or 1
    below = width < height + 170  # narrow box: legend under the pie
    if below:
        r = min(width - 20, height * 0.62) / 2
        cx, cy = width / 2, r + 8
    else:
        cx, cy, r = height / 2, height / 2, height / 2 - 10
    out, angle = [], -math.pi / 2
    fills = colors(accent, len(values))
    for i, value in enumerate(values):
        share = max(value, 0) / total
        if share <= 0:
            continue
        end = angle + share * 2 * math.pi
        if share >= 0.9999:
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fills[i]}"/>')
        else:
            x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
            x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
            large = 1 if share > 0.5 else 0
            out.append(f'<path d="M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z" '
                       f'fill="{fills[i]}"><title>{escape(labels[i])}: {_fmt(value)}</title></path>')
        angle = end
    if donut:
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * 0.55:.1f}" fill="#fff"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" font-size="16" font-weight="bold">'
                   f'{_fmt(total)}</text>')
    if below:
        legend_x, top, room = 8, cy + r + 18, max(int((height - cy - r - 10) / 16), 1)
        shown = labels[:room]
        for i, label in enumerate(shown):
            y = top + i * 16
            out.append(f'<rect x="{legend_x}" y="{y - 9:.1f}" width="10" height="10" rx="2" fill="{fills[i]}"/>')
            out.append(f'<text x="{legend_x + 15}" y="{y:.1f}" fill="#333">{escape(_short(label, int(width / 7)))} '
                       f'({_fmt(values[i])})</text>')
        return out
    legend_x = height + 16
    for i, label in enumerate(labels[:12]):
        y = 18 + i * 20
        out.append(f'<rect x="{legend_x}" y="{y - 10}" width="12" height="12" rx="2" fill="{fills[i]}"/>')
        out.append(f'<text x="{legend_x + 18}" y="{y}" fill="#333">{escape(_short(label, 28))} '
                   f'({_fmt(values[i])})</text>')
    return out


def png(kind, labels, values, accent='#714B67', width=900, height=450):
    """A simple raster version for Word (python-docx cannot embed SVG)."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    if not labels:
        draw.text((20, height // 2), 'No data', fill='#777777')
    elif kind in ('pie', 'donut'):
        total = sum(v for v in values if v > 0) or 1
        box = (20, 20, height - 20, height - 20)
        start = -90.0
        fills = colors(accent, len(values))
        for i, value in enumerate(values):
            extent = 360.0 * max(value, 0) / total
            if extent:
                draw.pieslice(box, start, start + extent, fill=fills[i])
            start += extent
        if kind == 'donut':
            inset = (height - 40) * 0.225
            draw.ellipse((20 + inset, 20 + inset, height - 20 - inset, height - 20 - inset), fill='white')
        for i, label in enumerate(labels[:12]):
            y = 30 + i * 28
            draw.rectangle((height + 10, y, height + 26, y + 16), fill=fills[i])
            draw.text((height + 34, y), f'{_short(label, 30)} ({_fmt(values[i])})', fill='#333333')
    else:
        left, bottom, top = 70, 50, 20
        vmax = _axis_max([float(v or 0) for v in values])
        plot_w, plot_h = width - left - 20, height - top - bottom
        step = plot_w / len(values)
        previous = None
        for i, (label, value) in enumerate(zip(labels, values)):
            h = plot_h * float(value or 0) / vmax
            x = left + step * i
            if kind == 'line':
                point = (x + step / 2, top + plot_h - h)
                if previous:
                    draw.line([previous, point], fill=accent, width=4)
                draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill=accent)
                previous = point
            else:
                bar = max(step * 0.7, 2)
                draw.rectangle((x + (step - bar) / 2, top + plot_h - h, x + (step + bar) / 2, top + plot_h), fill=accent)
            draw.text((x + 4, height - bottom + 10), _short(label, max(int(step / 8), 4)), fill='#555555')
        for i in range(5):
            y = top + plot_h - plot_h * i / 4
            draw.line((left, y, width - 20, y), fill='#e5e5e5')
            draw.text((6, y - 6), _fmt(vmax * i / 4), fill='#777777')
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()
