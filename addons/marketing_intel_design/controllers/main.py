from odoo import http
from odoo.http import request

from ..models import render


class DesignController(http.Controller):

    @http.route('/marketing_intel_design/<int:design_id>/<any(png,pdf):kind>', type='http', auth='user',
                methods=['GET'], readonly=True)
    def download(self, design_id, kind):
        """Download PNG / Download PDF of a design the person may read (board 13.3)."""
        design = request.env['mi.design'].browse(design_id).exists()
        if not design:
            raise request.not_found()
        design.check_access('read')
        name, content_type, content = design._export(kind)
        return request.make_response(content, headers=[
            ('Content-Type', content_type),
            ('Content-Disposition', http.content_disposition(name)),
            ('Cache-Control', 'no-store'),
        ])

    @http.route('/marketing_intel_design/template/<int:template_id>/<string:fmt>', type='http', auth='user',
                methods=['GET'], readonly=True)
    def template_sample(self, template_id, fmt, brand_id=0, **kwargs):
        """The tile of a template in the New design dialog (board 13.2), drawn with the brand kit."""
        template = request.env['mi.design.template'].browse(template_id).exists()
        if not template or fmt not in dict(request.env['mi.design']._fields['format'].selection):
            raise request.not_found()
        brand = request.env['mi.brand'].browse(int(brand_id or 0)).exists()
        if brand:
            brand.check_access('read')
        return request.make_response(template._sample(fmt, brand), headers=[
            ('Content-Type', 'image/png'), ('Cache-Control', 'private, max-age=300')])

    @http.route('/marketing_intel_design/<int:design_id>/editor', type='http', auth='user', methods=['GET'],
                readonly=True)
    def editor_picture(self, design_id, w=1080, **kwargs):
        """The picture of a free design for the editor's canvas (board 16.1), drawn as it will be exported."""
        design = request.env['mi.design'].browse(design_id).exists()
        if not design:
            raise request.not_found()
        design.check_access('read')
        width = min(max(int(w or 0) or 1080, 120), 2480)
        image = design._render_slide(design.slide_ids[:1], width)
        return request.make_response(render.png(image), headers=[
            ('Content-Type', 'image/png'), ('Cache-Control', 'no-store')])
