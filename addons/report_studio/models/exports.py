"""Excel, PowerPoint and Word renderings of a report board.

Boxes keep their place on the 4-column grid: a row holds boxes until their
widths add up to 4. Page size, orientation and scaling follow the report.
"""

import base64
import io

from . import charts

XLSX_PAPER = {'A5': 11, 'A4': 9, 'A3': 8, 'Letter': 1, 'Legal': 5, 'Tabloid': 3}
COLS_PER_UNIT = 3  # Excel columns per grid column


def rows(blocks):
    """Greedy grid packing: [(box, start_column, span)] per row, 4 columns wide."""
    result, current, used = [], [], 0
    for box in blocks:
        span = max(1, min(4, box['width']))
        if used + span > 4 and current:
            result.append(current)
            current, used = [], 0
        current.append((box, used, span))
        used += span
    if current:
        result.append(current)
    return result


def _absolute(url, base_url):
    """Office files need absolute links; /odoo/... becomes https://your-server/odoo/..."""
    return (base_url or '').rstrip('/') + url if url.startswith('/') else url


def _image_bytes(box):
    try:
        return base64.b64decode(box['image']) if box.get('image') else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------- Excel

def xlsx(data):
    import xlsxwriter
    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {'in_memory': True})
    sheet = book.add_worksheet('Report')
    values_sheet = book.add_worksheet('Chart data')
    accent = data['accent']
    fmt = {
        'title': book.add_format({'bold': True, 'font_size': 18, 'font_color': accent}),
        'sub': book.add_format({'font_color': '#666666'}),
        'heading': book.add_format({'bold': True, 'font_size': 14, 'font_color': accent, 'bottom': 2,
                                    'bottom_color': accent}),
        'box_title': book.add_format({'bold': True, 'font_size': 11}),
        'number': book.add_format({'bold': True, 'font_size': 22, 'align': 'left', 'valign': 'vcenter',
                                   'top': 5, 'top_color': accent}),
        'text': book.add_format({'text_wrap': True, 'valign': 'top'}),
        'head': book.add_format({'bold': True, 'bg_color': '#EEEEEE', 'border': 1, 'text_wrap': True}),
        'cell': book.add_format({'border': 1, 'valign': 'top'}),
        'link': book.add_format({'font_color': '#1155CC', 'underline': 1}),
        'error': book.add_format({'font_color': '#B00020', 'italic': True, 'text_wrap': True}),
    }
    page = data['page']
    sheet.set_paper(XLSX_PAPER.get(page['paper'], 9))
    if page['orientation'] == 'landscape':
        sheet.set_landscape()
    sheet.set_margins(left=0.4, right=0.4, top=0.4, bottom=0.4)
    if page['fit'] in ('fit', 'fill'):
        sheet.fit_to_pages(1, 1)
    else:
        sheet.fit_to_pages(1, 0)
    sheet.set_column(0, 4 * COLS_PER_UNIT - 1, 11)
    sheet.write(0, 0, data['title'], fmt['title'])
    sheet.write(1, 0, ' · '.join(filter(None, [data['subtitle'], data['company'], str(data['date'])])), fmt['sub'])
    row = 3
    data_row = 0
    for line in rows(data['blocks']):
        heights = []
        for box, start, span in line:
            first, last = start * COLS_PER_UNIT, (start + span) * COLS_PER_UNIT - 1
            used, data_row = _xlsx_box(book, sheet, values_sheet, fmt, box, row, first, last, data_row, accent,
                                       data.get('base_url'))
            heights.append(used)
        row += max(heights) + 1
    sheet.print_area(0, 0, max(row, 1), 4 * COLS_PER_UNIT - 1)
    book.close()
    return buffer.getvalue()


def _xlsx_box(book, sheet, values_sheet, fmt, box, row, first, last, data_row, accent, base_url=''):
    """Write one box at (row, first..last); returns (rows used, next free chart-data row)."""
    start = row
    if box['type'] == 'heading':
        sheet.merge_range(row, first, row, last, box['title'], fmt['heading'])
        return 1, data_row
    if box['title']:
        sheet.merge_range(row, first, row, last, box['title'], fmt['box_title']) if last > first else \
            sheet.write(row, first, box['title'], fmt['box_title'])
        row += 1
    if box['error']:
        sheet.merge_range(row, first, row + 1, last, box['error'], fmt['error'])
        return row + 2 - start, data_row
    kind = box['type']
    if kind == 'kpi':
        sheet.merge_range(row, first, row + 1, last, box['display'], fmt['number'])
        row += 2
    elif kind == 'text':
        lines = max(2, min(30, len(box['text']) // (12 * (last - first + 1)) + box['text'].count('\n') + 1))
        sheet.merge_range(row, first, row + lines - 1, last, box['text'], fmt['text'])
        row += lines
    elif kind in ('table', 'view') and box['columns'] and not box.get('chart'):
        columns = box['columns'][:last - first + 1]
        for col, name in enumerate(columns):
            sheet.write(row, first + col, name, fmt['head'])
        row += 1
        for values in box['rows']:
            for col, value in enumerate(values[:len(columns)]):
                sheet.write(row, first + col, value, fmt['cell'])
            row += 1
    elif kind == 'list':
        for item in box['items']:
            sheet.write(row, first, f'• {item}')
            row += 1
    elif box.get('chart'):
        chart_data = box['chart']
        labels, values = chart_data['labels'], chart_data['values']
        values_sheet.write(data_row, 0, box['title'] or chart_data['measure'])
        for i, (label, value) in enumerate(zip(labels, values), 1):
            values_sheet.write(data_row + i, 0, label)
            values_sheet.write(data_row + i, 1, value)
        if labels:
            kind_map = {'bar': ('column', None), 'hbar': ('bar', None), 'line': ('line', None),
                        'pie': ('pie', None), 'donut': ('doughnut', None)}
            chart = book.add_chart({'type': kind_map.get(chart_data['kind'], ('column', None))[0]})
            chart.add_series({
                'name': chart_data['measure'],
                'categories': ['Chart data', data_row + 1, 0, data_row + len(labels), 0],
                'values': ['Chart data', data_row + 1, 1, data_row + len(labels), 1],
                'fill': {'color': accent} if chart_data['kind'] not in ('pie', 'donut') else {},
                'line': {'color': accent} if chart_data['kind'] == 'line' else {},
            })
            chart.set_legend({'none': chart_data['kind'] not in ('pie', 'donut')})
            chart.set_title({'none': True})
            width_px = (last - first + 1) * 80
            chart.set_size({'width': width_px, 'height': 280})
            sheet.insert_chart(row, first, chart)
            row += 14
        data_row += len(labels) + 2
    elif kind == 'image':
        image = _image_bytes(box)
        if image:
            sheet.insert_image(row, first, 'image', {'image_data': io.BytesIO(image), 'x_scale': 0.5, 'y_scale': 0.5,
                                                    'object_position': 1})
            row += 12
    elif kind == 'link' and box['url']:
        sheet.write_url(row, first, _absolute(box['url'], base_url), fmt['link'], box['link_label'])
        row += 1
    return max(row - start, 1), data_row


# ---------------------------------------------------------------------- PowerPoint

def pptx(data):
    try:
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.util import Emu, Mm, Pt
    except ImportError:
        from .report import _missing
        _missing('python-pptx')
    page = data['page']
    deck = Presentation()
    deck.slide_width, deck.slide_height = Mm(page['width_mm']), Mm(page['height_mm'])
    blank = deck.slide_layouts[6]
    margin, gap = Mm(10), Mm(4)
    usable_w = deck.slide_width - 2 * margin
    unit = (usable_w - 3 * gap) / 4
    accent = RGBColor.from_string(data['accent'].lstrip('#')[:6].upper().ljust(6, '0'))
    chart_types = {'bar': XL_CHART_TYPE.COLUMN_CLUSTERED, 'hbar': XL_CHART_TYPE.BAR_CLUSTERED,
                   'line': XL_CHART_TYPE.LINE_MARKERS, 'pie': XL_CHART_TYPE.PIE, 'donut': XL_CHART_TYPE.DOUGHNUT}

    def box_height(box, span):
        kind = box['type']
        if kind == 'heading':
            return Mm(12)
        base = Mm(8) if box['title'] else 0
        if box['error']:
            return base + Mm(14)
        if kind == 'kpi':
            return base + Mm(22)
        if kind == 'text':
            chars_per_line = max(span * 28, 20)
            return base + Mm(6) * min(18, max(2, len(box['text']) // chars_per_line + box['text'].count('\n') + 1))
        if box.get('chart') or kind == 'image':
            return base + Mm(60 if span > 1 else 45)
        if box['columns']:
            return base + Mm(7) * (min(len(box['rows']), 15) + 1)
        if kind == 'list':
            return base + Mm(6) * max(1, min(len(box['items']), 15))
        return base + Mm(10)

    header_h = Mm(18)
    layout = []  # (box, start, span, height)
    for line in rows(data['blocks']):
        height = max(box_height(box, span) for box, _s, span in line)
        layout.append((line, height))
    total = header_h + sum(h for _l, h in layout) + gap * len(layout)
    available = deck.slide_height - 2 * margin
    scale = 1.0
    if page['fit'] == 'fit' and total > available:
        scale = available / total
    elif page['fit'] == 'fill' and total:
        scale = available / total

    def new_slide(first):
        slide = deck.slides.add_slide(blank)
        y = margin
        if first:
            title = slide.shapes.add_textbox(margin, y, usable_w, Mm(10)).text_frame
            title.text = data['title']
            title.paragraphs[0].runs[0].font.size = Pt(24)
            title.paragraphs[0].runs[0].font.bold = True
            title.paragraphs[0].runs[0].font.color.rgb = accent
            sub = title.add_paragraph()
            sub.text = ' · '.join(filter(None, [data['subtitle'], data['company'], str(data['date'])]))
            sub.runs[0].font.size = Pt(11)
            y += Emu(int(header_h * min(scale, 1.0)))
        return slide, y

    slide, y = new_slide(True)
    for line, height in layout:
        height = Emu(int(height * scale))
        if page['fit'] == 'actual' and y + height > deck.slide_height - margin and y > margin + Mm(1):
            slide, y = new_slide(False)
        for box, start, span in line:
            x = margin + (unit + gap) * start
            w = unit * span + gap * (span - 1)
            _pptx_box(slide, box, Emu(int(x)), Emu(int(y)), Emu(int(w)), height, accent, chart_types,
                      CategoryChartData, XL_LEGEND_POSITION, Pt, Mm, scale, data.get('base_url'))
        y += height + Emu(int(gap * scale))
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def _pptx_box(slide, box, x, y, w, h, accent, chart_types, CategoryChartData, XL_LEGEND_POSITION, Pt, Mm, scale,
              base_url=''):
    size = max(scale, 0.5)
    kind = box['type']
    top = y
    if kind == 'heading':
        frame = slide.shapes.add_textbox(x, y, w, h).text_frame
        frame.text = box['title']
        run = frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold, run.font.color.rgb = Pt(18 * size), True, accent
        return
    if box['title']:
        frame = slide.shapes.add_textbox(x, y, w, Mm(7)).text_frame
        frame.text = box['title']
        frame.paragraphs[0].runs[0].font.size = Pt(12 * size)
        frame.paragraphs[0].runs[0].font.bold = True
        top = y + int(Mm(8) * scale)
    body_h = max(h - (top - y), Mm(5))
    if box['error']:
        frame = slide.shapes.add_textbox(x, top, w, body_h).text_frame
        frame.word_wrap = True
        frame.text = box['error']
        return
    if kind == 'kpi':
        frame = slide.shapes.add_textbox(x, top, w, body_h).text_frame
        frame.text = box['display']
        run = frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold, run.font.color.rgb = Pt(32 * size), True, accent
    elif kind == 'text':
        frame = slide.shapes.add_textbox(x, top, w, body_h).text_frame
        frame.word_wrap = True
        frame.text = box['text'][:3000]
        for paragraph in frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(11 * size)
    elif box.get('chart'):
        chart = box['chart']
        if chart['labels']:
            chart_data = CategoryChartData()
            chart_data.categories = [str(label) for label in chart['labels']]
            chart_data.add_series(chart['measure'], chart['values'])
            graphic = slide.shapes.add_chart(chart_types.get(chart['kind'], chart_types['bar']), x, top, w, body_h,
                                             chart_data).chart
            graphic.has_title = False
            graphic.has_legend = chart['kind'] in ('pie', 'donut')
            if graphic.has_legend:
                graphic.legend.position = XL_LEGEND_POSITION.RIGHT
                graphic.legend.include_in_layout = False
            elif chart['kind'] != 'line':
                graphic.plots[0].series[0].format.fill.solid()
                graphic.plots[0].series[0].format.fill.fore_color.rgb = accent
    elif box['columns']:
        shown = box['rows'][:15]
        table = slide.shapes.add_table(len(shown) + 1, len(box['columns']), x, top, w, body_h).table
        for col, name in enumerate(box['columns']):
            table.cell(0, col).text = str(name)
        for r, values in enumerate(shown, 1):
            for col, value in enumerate(values):
                table.cell(r, col).text = str(value)
        for cell_row in table.rows:
            for cell in cell_row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(9 * size)
    elif kind == 'list':
        frame = slide.shapes.add_textbox(x, top, w, body_h).text_frame
        frame.word_wrap = True
        frame.text = '\n'.join(f'• {item}' for item in box['items'][:15])
        for paragraph in frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(11 * size)
    elif kind == 'image':
        image = _image_bytes(box)
        if image:
            picture = slide.shapes.add_picture(io.BytesIO(image), x, top)
            ratio = min(w / picture.width, body_h / picture.height)
            picture.width, picture.height = int(picture.width * ratio), int(picture.height * ratio)
    elif kind == 'link' and box['url']:
        frame = slide.shapes.add_textbox(x, top, w, body_h).text_frame
        run = frame.paragraphs[0].add_run()
        run.text = box['link_label']
        run.hyperlink.address = _absolute(box['url'], base_url)
        run.font.size = Pt(12 * size)


# ---------------------------------------------------------------------- Word

def docx(data):
    try:
        import docx as docx_lib
        from docx.enum.section import WD_ORIENT
        from docx.shared import Mm, Pt, RGBColor
    except ImportError:
        from .report import _missing
        _missing('python-docx')
    page = data['page']
    document = docx_lib.Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE if page['orientation'] == 'landscape' else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Mm(page['width_mm']), Mm(page['height_mm'])
    for side in ('left_margin', 'right_margin', 'top_margin', 'bottom_margin'):
        setattr(section, side, Mm(page['margin_mm']))
    accent = RGBColor.from_string(data['accent'].lstrip('#')[:6].upper().ljust(6, '0'))
    heading = document.add_heading(data['title'], 0)
    for run in heading.runs:
        run.font.color.rgb = accent
    document.add_paragraph(' · '.join(filter(None, [data['subtitle'], data['company'], str(data['date'])])))
    usable_mm = page['width_mm'] - 2 * page['margin_mm']
    for line in rows(data['blocks']):
        if len(line) == 1 and line[0][2] == 4:
            _docx_box(document, line[0][0], usable_mm, accent, Mm, Pt, docx_lib, data.get('base_url'))
            continue
        table = document.add_table(rows=1, cols=4)
        table.autofit = False
        cells = table.rows[0].cells
        for box, start, span in line:
            cell = cells[start]
            if span > 1:
                cell = cell.merge(cells[start + span - 1])
            cell.paragraphs[0].text = ''
            _docx_box(cell, box, usable_mm * span / 4, accent, Mm, Pt, docx_lib, data.get('base_url'))
        document.add_paragraph()
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _docx_box(container, box, width_mm, accent, Mm, Pt, docx_lib, base_url=''):
    kind = box['type']
    paragraph = container.paragraphs[0] if hasattr(container, 'merge') and not container.paragraphs[0].text else None

    def para(text='', bold=False, size=None, color=None):
        nonlocal paragraph
        target = paragraph if paragraph is not None else container.add_paragraph()
        paragraph = None
        run = target.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color
        return target

    if kind == 'heading':
        if hasattr(container, 'add_heading'):
            heading = container.add_heading(box['title'], 1)
            for run in heading.runs:
                run.font.color.rgb = accent
        else:
            para(box['title'], bold=True, size=15, color=accent)
        return
    if box['title']:
        para(box['title'], bold=True, size=12)
    if box['error']:
        para(box['error'])
        return
    if kind == 'kpi':
        para(box['display'], bold=True, size=26, color=accent)
    elif kind == 'text':
        for chunk in box['text'].split('\n\n'):
            if chunk.strip():
                para(chunk.strip())
    elif box.get('chart'):
        chart = box['chart']
        try:
            image = charts.png(chart['kind'], chart['labels'], chart['values'], '#' + str(accent))
        except ImportError:
            image = None
        if image:
            para().add_run().add_picture(io.BytesIO(image), width=Mm(max(width_mm - 4, 30)))
    elif box['columns']:
        table = container.add_table(rows=1, cols=len(box['columns']))
        table.style = 'Light Grid Accent 1'
        for col, name in enumerate(box['columns']):
            table.rows[0].cells[col].text = str(name)
        for values in box['rows']:
            cells = table.add_row().cells
            for col, value in enumerate(values):
                cells[col].text = str(value)
    elif kind == 'list':
        for item in box['items']:
            para(f'• {item}')
    elif kind == 'image':
        image = _image_bytes(box)
        if image:
            para().add_run().add_picture(io.BytesIO(image), width=Mm(max(min(width_mm - 4, 160), 20)))
    elif kind == 'link' and box['url']:
        url = _absolute(box['url'], base_url)
        para(f"{box['link_label']} ({url})" if box['link_label'] != box['url'] else url)
