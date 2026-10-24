from odoo import http
from odoo.http import request


class ReportStudio(http.Controller):

    @http.route('/report_studio/<int:report_id>/<string:fmt>', type='http', auth='user', methods=['GET'])
    def export(self, report_id, fmt, **kwargs):
        report = request.env['report.studio.report'].browse(report_id).exists()
        if not report or fmt not in ('pdf', 'xlsx', 'pptx', 'docx', 'html'):
            raise request.not_found()
        filename, mimetype, content = report._export(fmt)
        disposition = 'inline' if fmt == 'html' else 'attachment'
        return request.make_response(content, headers=[
            ('Content-Type', mimetype), ('Content-Length', len(content)),
            ('Content-Disposition', http.content_disposition(filename, disposition_type=disposition)),
            ('X-Content-Type-Options', 'nosniff')])
