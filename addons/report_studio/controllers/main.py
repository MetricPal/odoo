import json

from markupsafe import escape

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.http.stream import content_disposition


class ReportStudio(http.Controller):

    @http.route('/report_studio/<int:report_id>/<string:fmt>', type='http', auth='user', methods=['GET'])
    def export(self, report_id, fmt, **kwargs):
        report = request.env['report.studio.report'].browse(report_id).exists()
        if not report or fmt not in ('pdf', 'xlsx', 'pptx', 'docx', 'html'):
            raise request.not_found()
        try:
            filename, mimetype, content = report._export(fmt)
        except UserError as error:
            # A readable page instead of "Internal Server Error" (e.g. a missing export package).
            body = f'<html><body style="font-family:sans-serif;padding:2rem"><h2>Export not available</h2><p>{escape(str(error))}</p></body></html>'
            return request.make_response(body, status=400, headers=[('Content-Type', 'text/html; charset=utf-8')])
        disposition = 'inline' if fmt == 'html' else 'attachment'
        return request.make_response(content, headers=[
            ('Content-Type', mimetype), ('Content-Length', len(content)),
            ('Content-Disposition', content_disposition(filename, disposition_type=disposition)),
            ('X-Content-Type-Options', 'nosniff')])

    @http.route('/report_studio/add_view', type='jsonrpc', auth='user')
    def add_view(self, action_id, context_to_save, domain, view_mode, name='', report_id=False, new_report=''):
        """Add the current list, graph or pivot (with its filters and grouping) as a box of a report."""
        Report = request.env['report.studio.report']
        if new_report:
            report = Report.create({'name': new_report})
        else:
            report = Report.browse(int(report_id)).exists()
            if not report:
                raise request.not_found()
        report.check_access('write')
        action = request.env['ir.actions.act_window'].browse(int(action_id)).exists()
        if not action:
            raise UserError(_('This view cannot be added to a report.'))
        res_model = action.sudo().res_model
        if res_model not in request.env or not request.env[res_model].has_access('read'):
            raise UserError(_('This view cannot be added to a report.'))
        context = {key: value for key, value in (context_to_save or {}).items()
                   if key in ('group_by', 'graph_measure', 'graph_mode', 'graph_groupbys', 'pivot_measures',
                              'pivot_row_groupby', 'pivot_column_groupby')}
        view_type = view_mode if view_mode in ('list', 'graph', 'pivot', 'kanban') else 'list'
        last = max(report.block_ids.mapped('sequence') or [0])
        request.env['report.studio.block'].create({
            'report_id': report.id, 'type': 'view', 'title': name or action.name, 'sequence': last + 1,
            'res_model': res_model, 'action_id': action.id, 'view_type': view_type,
            'domain': repr(domain or []), 'context': json.dumps(context),
            'width': 2 if view_type == 'graph' else 4,
        })
        return {'report_id': report.id, 'report_name': report.name}
