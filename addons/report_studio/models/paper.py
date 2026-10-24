"""Report Studio PDFs use the paper size, orientation and margins chosen on each report."""

from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def get_paperformat(self):
        page = self.env.context.get('report_studio_page')
        if page and self.report_name == 'report_studio.report_pdf':
            return self.env['report.paperformat'].sudo()._report_studio_format(page)
        return super().get_paperformat()


class ReportPaperformat(models.Model):
    _inherit = 'report.paperformat'

    def _report_studio_format(self, page):
        name = f"Report Studio {page['paper']} {page['orientation']}"
        paper = self.search([('name', '=', name)], limit=1)
        if not paper:
            margin = page['margin_mm']
            paper = self.create({
                'name': name, 'format': page['paper'],
                'orientation': 'Landscape' if page['orientation'] == 'landscape' else 'Portrait',
                'margin_top': margin, 'margin_bottom': margin, 'margin_left': margin, 'margin_right': margin,
                'header_line': False, 'header_spacing': 0, 'dpi': 96, 'disable_shrinking': True,
            })
        return paper
