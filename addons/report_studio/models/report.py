"""Reports as boards of boxes on a 4-column grid, rendered once and exported to several formats.

A box holds a title, text, number, chart, table, list, image, hyperlink or a
view added from any app (list, graph or pivot with its filters). It spans 1 to
4 columns. Every number comes from a query run with the reader's own access
rights. Filters are literal lists only (no code), fields must exist, sort is
one field, rows are capped. The page (A5, A4, A3, Letter, Legal, Tabloid;
portrait or landscape; actual size, fit or fill) is used by the board and by
every export.
"""

import ast
import base64
import hashlib
import json
import logging
import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext

from . import charts

_logger = logging.getLogger(__name__)

MAX_ROWS = 500
BLOCK_TYPES = [('heading', 'Title'), ('text', 'Text'), ('kpi', 'Number'), ('chart', 'Chart'), ('table', 'Table'),
               ('list', 'List'), ('image', 'Image'), ('link', 'Hyperlink'), ('view', 'View from an app')]
DATA_TYPES = ('kpi', 'chart', 'table', 'list', 'view')
DEFAULT_WIDTH = {'kpi': 1, 'link': 1, 'image': 2, 'chart': 2, 'list': 2}
MEASURES = [('count', 'Number of records'), ('sum', 'Sum of a field'), ('avg', 'Average of a field')]
INTERVALS = [('day', 'Day'), ('week', 'Week'), ('month', 'Month'), ('quarter', 'Quarter'), ('year', 'Year')]
PAPERS = {'A5': (148, 210), 'A4': (210, 297), 'A3': (297, 420), 'Letter': (215.9, 279.4),
          'Legal': (215.9, 355.6), 'Tabloid': (279.4, 431.8)}
PAPER_SELECTION = [('A5', 'A5'), ('A4', 'A4'), ('A3', 'A3'), ('Letter', 'Letter'), ('Legal', 'Legal'),
                   ('Tabloid', 'Tabloid')]
FITS = [('actual', 'Actual size (several pages)'), ('fit', 'Fit on one page'), ('fill', 'Fill the page')]
MARGIN_MM = 10


class Report(models.Model):
    _name = 'report.studio.report'
    _description = 'Report'
    _inherit = ['mail.thread.main.attachment']
    _order = 'write_date desc, id desc'

    name = fields.Char(required=True, tracking=True)
    subtitle = fields.Char()
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, string='Owner')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    shared = fields.Boolean(help='Everyone in the company can open, edit and export this report.')
    accent_color = fields.Char(default='#714B67', string='Accent colour')
    paper = fields.Selection(PAPER_SELECTION, default='A4', required=True, string='Page size')
    orientation = fields.Selection([('portrait', 'Portrait'), ('landscape', 'Landscape')], default='portrait',
                                   required=True)
    fit = fields.Selection(FITS, default='actual', required=True, string='Scaling',
                           help='Actual size: content flows over several pages. Fit: shrink to one page. '
                                'Fill: one page, boxes stretched to fill it.')
    block_ids = fields.One2many('report.studio.block', 'report_id', copy=True, string='Boxes')
    box_count = fields.Integer(compute='_compute_box_count')
    board_data = fields.Json(compute='_compute_board_data', string='Board')
    preview_html = fields.Html(compute='_compute_preview', sanitize=False, string='Preview')
    res_model = fields.Char(readonly=True, help='Record this report was generated for, if any.')
    res_id = fields.Integer(readonly=True)
    preview_attachment_id = fields.Many2one('ir.attachment', readonly=True, copy=False, string='Preview file')
    preview_signature = fields.Char(readonly=True, copy=False)

    @api.depends('block_ids')
    def _compute_box_count(self):
        for report in self:
            report.box_count = len(report.block_ids)

    def _page(self):
        width, height = PAPERS.get(self.paper or 'A4', PAPERS['A4'])
        if self.orientation == 'landscape':
            width, height = height, width
        return {'paper': self.paper or 'A4', 'orientation': self.orientation or 'portrait', 'fit': self.fit or 'actual',
                'width_mm': width, 'height_mm': height, 'margin_mm': MARGIN_MM,
                'content_height_px': round((height - 2 * MARGIN_MM) * 96 / 25.4),
                'content_width_px': round((width - 2 * MARGIN_MM) * 96 / 25.4),
                'content_ratio': round((height - 2 * MARGIN_MM) / (width - 2 * MARGIN_MM), 4)}

    @api.depends('name', 'subtitle', 'accent_color', 'paper', 'orientation', 'fit', 'block_ids',
                 'block_ids.sequence', 'block_ids.write_date', 'block_ids.width')
    def _compute_board_data(self):
        for report in self:
            data = report._data()
            report.board_data = {
                'page': data['page'], 'accent': data['accent'], 'title': data['title'],
                'subtitle': data['subtitle'], 'company': data['company'], 'date': str(data['date']),
                'boxes': [{'id': box['id'], 'type': box['type'], 'type_label': box['type_label'],
                           'width': box['width'], 'title': box['title'],
                           'html': str(self.env['ir.qweb']._render('report_studio.box_content',
                                                                         {'box': box, 'chart_svg': charts.svg}))}
                          for box in data['blocks']],
            }

    @api.depends('name', 'subtitle', 'accent_color', 'block_ids', 'block_ids.sequence', 'block_ids.write_date')
    def _compute_preview(self):
        for report in self:
            styles = self.env['ir.qweb']._render('report_studio.report_styles', {})
            report.preview_html = styles + report._render_html()

    # ------------------------------------------------------------------ data

    def _data(self):
        """Plain data for the page and every box, shared by all renderers."""
        self.ensure_one()
        from .exports import rows
        blocks = [block._safe_data() for block in self.block_ids.sorted(lambda b: (b.sequence, b.id))]
        page = self._page()
        grid = rows(blocks)
        return {
            'title': self.name or '', 'subtitle': self.subtitle or '', 'accent': self.accent_color or '#714B67',
            'company': self.company_id.name, 'date': fields.Date.context_today(self), 'page': page,
            'blocks': blocks, 'rows': grid, 'base_url': self.get_base_url(),
        }

    def _render_html(self, fixed_width=False):
        # The PDF gets a fixed width (printable width at 96 dpi) so its layout is known when the
        # fit script measures it; browsers use the page width.
        return self.env['ir.qweb']._render('report_studio.report_body', {
            'report': self._data(), 'chart_svg': charts.svg, 'fixed_width': fixed_width})

    # ------------------------------------------------------------------ board editing (called by the board widget)

    def action_add_box(self, box_type):
        self.ensure_one()
        self.check_access('write')
        if box_type not in dict(BLOCK_TYPES):
            raise UserError(_('Unknown box type.'))
        last = max(self.block_ids.mapped('sequence') or [0])
        block = self.env['report.studio.block'].create({
            'report_id': self.id, 'type': box_type, 'sequence': last + 1,
            'title': dict(BLOCK_TYPES)[box_type] if box_type != 'heading' else _('New section')})
        return block.id

    def action_reorder_boxes(self, block_ids):
        self.ensure_one()
        self.check_access('write')
        blocks = self.block_ids
        for sequence, block_id in enumerate(block_ids, 1):
            block = blocks.filtered(lambda b: b.id == block_id)
            if block:
                block.sequence = sequence
        return True

    # ------------------------------------------------------------------ exports

    def _export(self, fmt):
        self.ensure_one()
        self.check_access('read')
        from . import exports
        _check_library(fmt)
        data = self._data()
        stem = re.sub(r'[^\w-]+', '_', self.name).strip('_') or 'report'
        if fmt == 'html':
            styles = self.env['ir.qweb']._render('report_studio.report_styles', {})
            page = self.env['ir.qweb']._render('report_studio.report_page', {
                'report': data, 'body': self._render_html(), 'styles': styles})
            return f'{stem}.html', 'text/html; charset=utf-8', str(page).encode()
        if fmt == 'pdf':
            content, _kind = self.env['ir.actions.report'].with_context(
                report_studio_page=data['page'])._render_qweb_pdf('report_studio.action_report_pdf', self.ids)
            return f'{stem}.pdf', 'application/pdf', content
        if fmt == 'xlsx':
            return (f'{stem}.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    exports.xlsx(data))
        if fmt == 'pptx':
            return (f'{stem}.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    exports.pptx(data))
        if fmt == 'docx':
            return (f'{stem}.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    exports.docx(data))
        raise UserError(_('Unknown format: %s', fmt))

    def _download(self, fmt):
        self.ensure_one()
        _check_library(fmt)  # explain a missing package here, in the form, instead of on an error page
        return {'type': 'ir.actions.act_url', 'url': f'/report_studio/{self.id}/{fmt}', 'target': 'self'}

    def action_export(self, fmt):
        return self._download(fmt)

    def action_export_pdf(self):
        return self._download('pdf')

    def action_export_xlsx(self):
        return self._download('xlsx')

    def action_export_pptx(self):
        return self._download('pptx')

    def action_export_docx(self):
        return self._download('docx')

    def action_export_html(self):
        return self._download('html')

    # ------------------------------------------------------------------ side preview

    def _preview_signature(self):
        data = self._data()
        data.pop('date', None)
        return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()

    def action_refresh_preview(self):
        """Render the report as a PDF shown in the form's side preview; only when its content changed.

        Returns True when a new preview file was made.
        """
        self.ensure_one()
        self.check_access('write')
        signature = self._preview_signature()
        if signature == self.preview_signature and self.preview_attachment_id.exists():
            return False
        try:
            _name, _mime, content = self._export('pdf')
        except Exception as error:  # noqa: BLE001 - no PDF engine: the board still works, no side preview
            _logger.info('Report Studio preview not rendered for %s: %s', self.id, error)
            return False
        old = self.preview_attachment_id
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name or "Report"} (preview).pdf', 'raw': content, 'mimetype': 'application/pdf',
            'res_model': self._name, 'res_id': self.id,
        })
        self.write({'preview_attachment_id': attachment.id, 'preview_signature': signature,
                    'message_main_attachment_id': attachment.id})
        if old.exists():
            old.unlink()
        return True

    def action_open_board(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form'}


class Block(models.Model):
    _name = 'report.studio.block'
    _description = 'Report box'
    _order = 'sequence, id'

    report_id = fields.Many2one('report.studio.report', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    type = fields.Selection(BLOCK_TYPES, required=True, default='text', string='Box type')
    width = fields.Integer(default=4, string='Columns', help='How many of the 4 columns the box spans.')
    title = fields.Char()
    content = fields.Html(string='Text', sanitize=True)
    # Data source: a model chosen from the apps the person can open, filtered with a literal domain.
    res_model = fields.Char(string='Model name', help='Technical name of the model the box reads.')
    model_choice = fields.Selection(selection='_selection_models', string='Data from', compute='_compute_model_choice',
                                    inverse='_inverse_model_choice')
    model_id = fields.Many2one('ir.model', string='Model', ondelete='cascade', compute='_compute_model_id',
                               inverse='_inverse_model_id', store=True, readonly=False)
    model_name = fields.Char(compute='_compute_model_name')
    domain = fields.Char(default='[]', help='Which records, e.g. [("state", "=", "sale")]. Literal values only.')
    measure = fields.Selection(MEASURES, default='count', string='Show')
    measure_field = fields.Char(string='Field to add up', help='Technical name of a number field, e.g. amount_total.')
    prefix = fields.Char(help='Shown before the number, e.g. RM')
    suffix = fields.Char(help='Shown after the number, e.g. %')
    field_names = fields.Char(string='Columns', help='Technical field names separated by commas, e.g. name, date.')
    group_by = fields.Char(string='Group by', help='Field that makes the bars or slices, e.g. stage_id.')
    date_interval = fields.Selection(INTERVALS, default='month', string='Date grouping')
    chart_type = fields.Selection(charts.KINDS, default='bar', string='Chart')
    list_field = fields.Char(string='Show field', help='Field shown for each item; empty means the record name.')
    limit = fields.Integer(default=20, string='Rows')
    order = fields.Char(string='Sort by', help='e.g. date desc')
    image = fields.Binary(attachment=True)
    url = fields.Char(string='Address')
    link_label = fields.Char(string='Link text')
    # Views added from an app with "Add to report".
    action_id = fields.Many2one('ir.actions.act_window', string='From menu', ondelete='set null')
    view_type = fields.Selection([('list', 'List'), ('graph', 'Graph'), ('pivot', 'Pivot'), ('kanban', 'Kanban')])
    context = fields.Char(string='View settings', help='Grouping and measures saved with the view (JSON).')

    @api.model
    def _selection_models(self):
        """Main models behind the menus the person can open, plus models already used on boxes."""
        names = set()
        actions = self.env['ir.ui.menu'].search([('action', '!=', False)]).mapped('action')
        for action in actions:
            if action._name == 'ir.actions.act_window' and action.sudo().res_model:
                names.add(action.sudo().res_model)
        names |= set(self.sudo().search([('res_model', '!=', False)]).mapped('res_model'))
        result = []
        for name in names:
            if name in self.env and not self.env[name]._transient and not self.env[name]._abstract:
                if self.env[name].has_access('read'):
                    result.append((name, self.env[name]._description or name))
        return sorted(result, key=lambda item: item[1].lower())

    @api.depends('res_model')
    def _compute_model_choice(self):
        for block in self:
            block.model_choice = block.res_model or False

    @api.onchange('model_choice')
    def _onchange_model_choice(self):
        if self.model_choice and self.model_choice != self.res_model:
            self.res_model = self.model_choice
            self.domain = '[]'
            self.field_names = self.measure_field = self.group_by = self.list_field = False

    def _inverse_model_choice(self):
        for block in self:
            if block.model_choice:
                block.res_model = block.model_choice

    @api.depends('res_model')
    def _compute_model_id(self):
        for block in self:
            block.model_id = self.env['ir.model'].sudo()._get(block.res_model) if block.res_model else False

    def _inverse_model_id(self):
        for block in self:
            block.res_model = block.model_id.sudo().model if block.model_id else False

    @api.depends('res_model')
    def _compute_model_name(self):
        for block in self:
            block.model_name = block.res_model or ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'width' not in vals:
                vals['width'] = DEFAULT_WIDTH.get(vals.get('type', 'text'), 4)
            if vals.get('model_id') and not vals.get('res_model'):
                vals['res_model'] = self.env['ir.model'].sudo().browse(vals['model_id']).model
        return super().create(vals_list)

    @api.constrains('width')
    def _check_width(self):
        for block in self:
            if not 1 <= block.width <= 4:
                raise ValidationError(_('A box spans 1 to 4 columns.'))

    @api.constrains('domain', 'res_model', 'field_names', 'measure_field', 'type', 'limit', 'order', 'group_by',
                    'list_field', 'measure', 'url')
    def _check_query(self):
        for block in self.filtered(lambda b: b.type in ('kpi', 'table', 'chart', 'list') and b.res_model):
            block._query_parts()
        for block in self.filtered(lambda b: b.type == 'link' and b.url):
            if not re.match(r'^(https?://|mailto:|/)', block.url.strip()):
                raise ValidationError(_('Links start with https://, http://, mailto: or /.'))

    # ------------------------------------------------------------------ queries

    def _label(self):
        return self.title or dict(BLOCK_TYPES).get(self.type, self.type)

    def _query_parts(self):
        """Validated (model, domain, column names) for this box, read with the current user's rights."""
        if not self.res_model:
            raise ValidationError(_('Choose where the data of “%s” comes from.', self._label()))
        if self.res_model not in self.env:
            raise ValidationError(_('The app behind “%s” is not installed.', self._label()))
        Model = self.env[self.res_model]
        domain = _literal_domain(self.domain, self._label())
        names = self._column_names()
        checks = list(names)
        if self.type in ('kpi', 'chart') and self.measure != 'count':
            checks.append(self.measure_field)
        if self.type == 'chart':
            checks.append(self.group_by)
        if self.type == 'list' and self.list_field:
            checks.append(self.list_field)
        for name in checks:
            if not name or name not in Model._fields:
                raise ValidationError(_('“%(field)s” is not a field of %(model)s.', field=name or '?',
                                        model=Model._description))
        if self.type in ('kpi', 'chart') and self.measure != 'count' and Model._fields[self.measure_field].type not in (
                'integer', 'float', 'monetary'):
            raise ValidationError(_('Only number fields can be added up.'))
        if self.order and not re.fullmatch(r'\s*\w+(\s+(asc|desc))?\s*', self.order):
            raise ValidationError(_('Sort by one field, e.g. “date desc”.'))
        if not 0 < (self.limit or 0) <= MAX_ROWS:
            raise ValidationError(_('Tables show between 1 and %s rows.', MAX_ROWS))
        return Model, domain, names

    def _column_names(self):
        return [name.strip() for name in (self.field_names or '').split(',') if name.strip()]

    def _aggregate(self):
        return '__count' if self.measure == 'count' or not self.measure_field else f'{self.measure_field}:{self.measure}'

    def _measure_label(self, Model):
        if self.measure == 'count' or not self.measure_field:
            return _('Count')
        return Model._fields[self.measure_field].get_description(self.env)['string']

    def _series(self, Model, domain, group_by, aggregate, limit=24):
        """Labels and values grouped by one field (dates by interval), largest first for categories."""
        field = Model._fields[group_by.split(':')[0]]
        spec = group_by
        if field.type in ('date', 'datetime') and ':' not in group_by:
            spec = f'{group_by}:{self.date_interval or "month"}'
        groups = Model._read_group(domain, [spec], [aggregate])
        labels, values = [], []
        for key, value in groups:
            labels.append(_group_label(field, key, spec, Model.env))
            values.append(float(value or 0))
        if field.type not in ('date', 'datetime'):
            pairs = sorted(zip(labels, values), key=lambda pair: -pair[1])[:limit]
            labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
        return labels, values

    # ------------------------------------------------------------------ data per box

    def _safe_data(self):
        """Box data; a broken box shows its problem instead of breaking the whole report."""
        try:
            return self._data()
        except (UserError, ValidationError, AccessError, ValueError, KeyError) as error:
            data = self._base_data()
            data['error'] = str(error)
            return data

    def _base_data(self):
        return {'id': self.id, 'type': self.type, 'type_label': dict(BLOCK_TYPES).get(self.type, self.type),
                'title': self.title or '', 'width': max(1, min(4, self.width or 4)), 'text': '', 'html': Markup(''),
                'value': None, 'display': '', 'columns': [], 'rows': [], 'items': [], 'chart': None,
                'image': None, 'url': '', 'link_label': '', 'error': '', 'accent': self.report_id.accent_color or '#714B67'}

    def _data(self):
        self.ensure_one()
        data = self._base_data()
        if self.type == 'text':
            data['html'] = Markup(self.content or '')
            data['text'] = html2plaintext(self.content or '')
        elif self.type == 'kpi':
            Model, domain, _names = self._query_parts()
            if self.measure == 'count':
                value = Model.search_count(domain)
            else:
                value = Model._read_group(domain, [], [self._aggregate()])[0][0] or 0
            data['value'] = value
            number = f'{value:,.2f}' if isinstance(value, float) else f'{value:,}'
            data['display'] = '\u00a0'.join(filter(None, [(self.prefix or '').strip(), number, (self.suffix or '').strip()]))
        elif self.type == 'chart':
            Model, domain, _names = self._query_parts()
            labels, values = self._series(Model, domain, self.group_by, self._aggregate())
            data['chart'] = {'kind': self.chart_type or 'bar', 'labels': labels, 'values': values,
                             'measure': self._measure_label(Model)}
        elif self.type == 'table':
            Model, domain, names = self._query_parts()
            names = names or ['display_name']
            records = Model.search(domain, limit=self.limit, order=self.order or None)
            data['columns'] = [_field_string(Model, name) for name in names]
            data['rows'] = [[_cell(record, name) for name in names] for record in records]
        elif self.type == 'list':
            Model, domain, _names = self._query_parts()
            records = Model.search(domain, limit=self.limit, order=self.order or None)
            name = self.list_field or 'display_name'
            data['items'] = [_cell(record, name) for record in records]
        elif self.type == 'image':
            if self.image:
                value = self.image
                if hasattr(value, 'to_base64'):  # Odoo binary value (attachment-backed)
                    content = value.content
                    data['image'] = value.to_base64()
                else:  # plain base64 text or bytes
                    raw = value if isinstance(value, bytes) else str(value).encode()
                    content = base64.b64decode(raw)
                    data['image'] = raw.decode()
                data['image_mime'] = _image_mime(content[:64])
        elif self.type == 'link':
            data['url'] = (self.url or '').strip()
            data['link_label'] = self.link_label or self.url or ''
        elif self.type == 'view':
            self._view_data(data)
        return data

    def _view_data(self, data):
        """A list, graph or pivot added from an app, rendered with its saved filters and grouping."""
        if not self.res_model or self.res_model not in self.env:
            raise ValidationError(_('The app behind “%s” is not installed.', self._label()))
        Model = self.env[self.res_model]
        domain = _literal_domain(self.domain, self._label())
        context = _json_dict(self.context)
        group_bys = [g for g in (context.get('group_by') or []) if isinstance(g, str)]
        if self.view_type == 'graph':
            group_by = (context.get('graph_groupbys') or group_bys or [None])[0]
            measure = context.get('graph_measure') or '__count'
            if not group_by or group_by.split(':')[0] not in Model._fields:
                raise ValidationError(_('Group the graph by a field before adding it to a report.'))
            aggregate = '__count' if measure in ('__count', 'count', None) else f'{measure}:sum'
            if aggregate != '__count' and measure not in Model._fields:
                aggregate = '__count'
            labels, values = self._series(Model, domain, group_by, aggregate)
            kind = {'bar': 'bar', 'line': 'line', 'pie': 'pie'}.get(context.get('graph_mode'), 'bar')
            data['chart'] = {'kind': kind, 'labels': labels, 'values': values,
                             'measure': _field_string(Model, measure) if aggregate != '__count' else _('Count')}
        elif self.view_type == 'pivot' or group_bys:
            group_by = (context.get('pivot_row_groupby') or group_bys or [None])[0]
            if not group_by or group_by.split(':')[0] not in Model._fields:
                raise ValidationError(_('Group the pivot by a field before adding it to a report.'))
            measures = [m for m in (context.get('pivot_measures') or ['__count'])
                        if m == '__count' or (m in Model._fields and Model._fields[m].type in ('integer', 'float', 'monetary'))]
            measures = measures or ['__count']
            aggregates = ['__count' if m == '__count' else f'{m}:sum' for m in measures]
            field = Model._fields[group_by.split(':')[0]]
            spec = group_by if ':' in group_by or field.type not in ('date', 'datetime') else f'{group_by}:month'
            groups = Model._read_group(domain, [spec], aggregates, limit=self.limit or 50)
            data['columns'] = [field.get_description(self.env)['string']] + [
                _('Count') if m == '__count' else _field_string(Model, m) for m in measures]
            data['rows'] = [[_group_label(field, row[0], spec, Model.env)] + [_number(v) for v in row[1:]] for row in groups]
        else:
            names = _list_view_fields(Model)
            records = Model.search(domain, limit=self.limit or 20, order=context.get('orderedBy_sql') or None)
            data['columns'] = [_field_string(Model, name) for name in names]
            data['rows'] = [[_cell(record, name) for name in names] for record in records]


# ---------------------------------------------------------------------- helpers

def _literal_domain(text, label):
    try:
        domain = ast.literal_eval(text or '[]')
    except (ValueError, SyntaxError):
        raise ValidationError(_('The filter of “%s” must be a list such as [("state", "=", "done")].', label)) from None
    if not isinstance(domain, list):
        raise ValidationError(_('The filter must be a list.'))
    return domain


def _json_dict(text):
    try:
        value = json.loads(text or '{}')
    except ValueError:
        try:
            value = ast.literal_eval(text or '{}')
        except (ValueError, SyntaxError):
            return {}
    return value if isinstance(value, dict) else {}


def _field_string(Model, name):
    if name in Model._fields:
        return Model._fields[name].get_description(Model.env)['string']
    return name


def _number(value):
    if isinstance(value, float):
        return round(value, 2)
    return value


def _group_label(field, key, spec, env):
    if key is False or key is None:
        return 'None'
    if field.type == 'many2one':
        return key.display_name or 'None'
    if field.type == 'selection':
        return dict(field._description_selection(env)).get(key, str(key))
    if field.type in ('date', 'datetime'):
        interval = spec.split(':')[1] if ':' in spec else 'month'
        formats = {'day': '%d %b %Y', 'week': 'W%V %Y', 'month': '%b %Y', 'quarter': None, 'year': '%Y'}
        if interval == 'quarter':
            return f'Q{(key.month - 1) // 3 + 1} {key.year}'
        return key.strftime(formats.get(interval) or '%b %Y')
    if field.type == 'boolean':
        return 'Yes' if key else 'No'
    return str(key)


def _list_view_fields(Model, limit=6):
    """Visible columns of the model's default list view."""
    try:
        arch = Model.get_views([(False, 'list')])['views']['list']['arch']
    except Exception:  # noqa: BLE001 - fall back to the record name
        return ['display_name']
    names = []
    for match in re.finditer(r'<field\s([^>]*)>', arch):
        attrs = match.group(1)
        name = re.search(r'name="([^"]+)"', attrs)
        if not name or name.group(1) not in Model._fields:
            continue
        if re.search(r'(column_invisible|invisible)="(1|True|true)"', attrs) or 'optional="hide"' in attrs:
            continue
        if Model._fields[name.group(1)].type in ('one2many', 'binary', 'html', 'properties', 'json'):
            continue
        if name.group(1) not in names:
            names.append(name.group(1))
        if len(names) >= limit:
            break
    return names or ['display_name']


def _image_mime(head):
    if head.startswith(b'\x89PNG'):
        return 'image/png'
    if head[:3] == b'GIF':
        return 'image/gif'
    if head.lstrip().startswith(b'<') or b'<svg' in head:
        return 'image/svg+xml'
    if head[:4] == b'RIFF':
        return 'image/webp'
    return 'image/jpeg'


def _cell(record, name):
    value = record[name]
    field = record._fields.get(name)
    if field is None:
        return str(value)
    if field.type in ('many2one',):
        return value.display_name or ''
    if field.type in ('one2many', 'many2many'):
        return ', '.join(value.mapped('display_name'))
    if field.type == 'selection':
        return dict(field._description_selection(record.env)).get(value, value or '')
    if field.type == 'boolean':
        return '✓' if value else ''
    if field.type == 'html':
        return html2plaintext(value or '')
    if value is False or value is None:
        return ''
    if field.type in ('date', 'datetime'):
        return fields.Date.to_string(value) if field.type == 'date' else fields.Datetime.to_string(value)
    return value


LIBRARIES = {'xlsx': ('xlsxwriter', 'xlsxwriter'), 'pptx': ('pptx', 'python-pptx'), 'docx': ('docx', 'python-docx')}


def _check_library(fmt):
    module, package = LIBRARIES.get(fmt, (None, None))
    if not module:
        return
    try:
        __import__(module)
    except ImportError:
        _missing(package)


def _missing(library):
    raise UserError(_('This export needs the Python package “%s” on the server. Ask your administrator to '
                      'install it (pip install %s).', library, library))
