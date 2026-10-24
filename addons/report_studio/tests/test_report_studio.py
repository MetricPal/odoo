import io
import zipfile

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestReportStudio(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'rs_user', groups='base.group_user')
        cls.other = new_test_user(cls.env, 'rs_other', groups='base.group_user')
        cls.partners = cls.env['res.partner'].create([{'name': f'RS Partner {i}', 'city': 'Ipoh'} for i in range(3)])
        partner_model = cls.env['ir.model']._get('res.partner')
        cls.report = cls.env['report.studio.report'].with_user(cls.user).create({
            'name': 'Partner brief', 'subtitle': 'Ipoh', 'block_ids': [
                (0, 0, {'type': 'heading', 'title': 'Overview', 'sequence': 1}),
                (0, 0, {'type': 'kpi', 'title': 'Partners in Ipoh', 'model_id': partner_model.id,
                        'domain': "[('city', '=', 'Ipoh')]", 'sequence': 2}),
                (0, 0, {'type': 'text', 'title': 'Summary', 'content': '<p>Three partners <b>in Ipoh</b>.</p>',
                        'sequence': 3}),
                (0, 0, {'type': 'table', 'title': 'List', 'model_id': partner_model.id,
                        'domain': "[('city', '=', 'Ipoh')]", 'field_names': 'name, city', 'order': 'name',
                        'limit': 10, 'sequence': 4}),
            ]})

    def test_data_and_preview(self):
        data = self.report._data()
        kpi = data['blocks'][1]
        self.assertEqual(kpi['value'], 3)
        table = data['blocks'][3]
        self.assertEqual(table['rows'][0], ['RS Partner 0', 'Ipoh'])
        self.assertIn('Partners in Ipoh', self.report.preview_html)
        self.assertIn('RS Partner 2', self.report.preview_html)

    def test_exports(self):
        name, mime, content = self.report._export('xlsx')
        self.assertTrue(name.endswith('.xlsx'))
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)))
        name, mime, content = self.report._export('html')
        self.assertIn(b'RS Partner 1', content)
        for fmt in ('pptx', 'docx'):
            try:
                name, mime, content = self.report._export(fmt)
            except Exception as error:  # library missing on this server
                self.assertIn('pip install', str(error))
            else:
                self.assertTrue(zipfile.is_zipfile(io.BytesIO(content)))

    def test_query_safety(self):
        block = self.report.block_ids.filtered(lambda b: b.type == 'table')
        with self.assertRaises(ValidationError):
            block.domain = "__import__('os').system('true')"
        with self.assertRaises(ValidationError):
            block.field_names = 'name, not_a_field'
        with self.assertRaises(ValidationError):
            block.order = 'name; drop table res_partner'
        with self.assertRaises(ValidationError):
            block.limit = 100000

    def test_private_unless_shared(self):
        Report = self.env['report.studio.report'].with_user(self.other)
        self.assertFalse(Report.search([('id', '=', self.report.id)]))
        self.report.shared = True
        self.assertTrue(Report.search([('id', '=', self.report.id)]))


@tagged('post_install', '-at_install')
class TestReportStudioDownload(HttpCase):
    def test_download_route_serves_each_format(self):
        admin = self.env.ref('base.user_admin')
        report = self.env['report.studio.report'].with_user(admin).create({
            'name': 'Download check', 'block_ids': [(0, 0, {'type': 'heading', 'title': 'Hello'})]})
        self.authenticate('admin', 'admin')
        formats = {'html': 'text/html', 'xlsx': 'spreadsheetml'}
        for fmt, mimetype in formats.items():
            response = self.url_open(f'/report_studio/{report.id}/{fmt}')
            self.assertEqual(response.status_code, 200, fmt)
            self.assertIn(mimetype, response.headers['Content-Type'])
        self.assertIn('Download check', self.url_open(f'/report_studio/{report.id}/html').text)
        self.assertEqual(self.url_open(f'/report_studio/{report.id}/exe').status_code, 404)
