import io
import zipfile
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
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


    def test_boxes_grid_and_page(self):
        report = self.report
        Block = self.env['report.studio.block'].with_user(self.user)
        chart = Block.create({'report_id': report.id, 'type': 'chart', 'title': 'By city', 'res_model': 'res.partner',
                              'domain': "[('city', '=', 'Ipoh')]", 'group_by': 'city', 'chart_type': 'donut',
                              'sequence': 5})
        listing = Block.create({'report_id': report.id, 'type': 'list', 'res_model': 'res.partner',
                                'domain': "[('city', '=', 'Ipoh')]", 'order': 'name', 'sequence': 6})
        link = Block.create({'report_id': report.id, 'type': 'link', 'url': 'https://metric.example',
                             'link_label': 'Open site', 'sequence': 7})
        pixel = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        image = Block.create({'report_id': report.id, 'type': 'image', 'image': pixel, 'sequence': 8})
        self.assertEqual((chart.width, listing.width, link.width, image.width), (2, 2, 1, 2), 'defaults per type')
        self.assertEqual(report.block_ids.filtered(lambda b: b.type == 'kpi').width, 1)
        with self.assertRaises(ValidationError):
            chart.width = 5
        with self.assertRaises(ValidationError):
            link.url = 'javascript:alert(1)'
        data = report._data()
        by_id = {box['id']: box for box in data['blocks']}
        self.assertEqual(by_id[chart.id]['chart']['values'], [3.0])
        self.assertEqual(by_id[listing.id]['items'][0], 'RS Partner 0')
        self.assertEqual(by_id[image.id]['image_mime'], 'image/png')
        # Rows hold boxes until their widths add up to 4 columns.
        self.assertEqual([[cell[2] for cell in row] for row in data['rows']], [[4], [1], [4], [4], [2, 2], [1, 2]])
        board = report.board_data
        self.assertEqual(board['page']['paper'], 'A4')
        self.assertTrue(any('<svg' in box['html'] for box in board['boxes']))
        # A broken box explains itself instead of breaking the report.
        self.env.cr.execute("UPDATE report_studio_block SET res_model = 'no.such.model' WHERE id = %s", [listing.id])
        listing.invalidate_recordset()
        self.assertIn('not installed', report._data()['blocks'][5]['error'])
        self.env.cr.execute("UPDATE report_studio_block SET res_model = 'res.partner' WHERE id = %s", [listing.id])
        listing.invalidate_recordset()
        # Page settings reach every format.
        report.write({'paper': 'A3', 'orientation': 'landscape', 'fit': 'fill'})
        page = report._page()
        self.assertEqual((page['width_mm'], page['height_mm']), (420, 297))
        paper = self.env['ir.actions.report'].with_context(report_studio_page=page)._get_report(
            'report_studio.action_report_pdf').get_paperformat()
        self.assertEqual((paper.format, paper.orientation), ('A3', 'Landscape'))
        _name, _mime, html = report._export('html')
        self.assertIn(b'size: 420mm 297mm', html)
        _name, _mime, content = report._export('xlsx')
        sheet = zipfile.ZipFile(io.BytesIO(content)).read('xl/worksheets/sheet1.xml')
        self.assertIn(b'orientation="landscape"', sheet)
        self.assertIn(b'paperSize="8"', sheet)
        for fmt, part in (('pptx', 'ppt/presentation.xml'), ('docx', 'word/document.xml')):
            try:
                _name, _mime, content = report._export(fmt)
            except UserError:
                continue
            xml = zipfile.ZipFile(io.BytesIO(content)).read(part)
            if fmt == 'pptx':
                self.assertIn(b'cx="15120000"', xml)  # 420 mm wide slide
            else:
                self.assertIn(b'w:orient="landscape"', xml)


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

    def test_missing_package_is_explained_not_a_server_error(self):
        admin = self.env.ref('base.user_admin')
        report = self.env['report.studio.report'].with_user(admin).create({'name': 'Missing package'})
        real_import = __import__

        def no_pptx(name, *args, **kwargs):
            if name == 'pptx' or name.startswith('pptx.'):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=no_pptx):
            with self.assertRaisesRegex(UserError, 'python-pptx'):
                report.action_export_pptx()
            self.authenticate('admin', 'admin')
            response = self.url_open(f'/report_studio/{report.id}/pptx')
        self.assertEqual(response.status_code, 400)
        self.assertIn('pip install python-pptx', response.text)

    def test_export_menu_action(self):
        admin = self.env.ref('base.user_admin')
        report = self.env['report.studio.report'].with_user(admin).create({'name': 'Export menu'})
        self.assertEqual(report.action_export('html')['url'], f'/report_studio/{report.id}/html')

    def test_add_view_from_any_app(self):
        admin = self.env.ref('base.user_admin')
        report = self.env['report.studio.report'].with_user(admin).create({'name': 'Board'})
        action = self.env.ref('base.action_partner_form')
        self.authenticate('admin', 'admin')
        result = self.make_jsonrpc_request('/report_studio/add_view', {
            'action_id': action.id, 'context_to_save': {'group_by': ['country_id'], 'graph_measure': '__count',
                                                         'graph_mode': 'pie', 'search_default_x': 1},
            'domain': [['is_company', '=', True]], 'view_mode': 'graph', 'name': 'Companies by country',
            'report_id': report.id})
        self.assertEqual(result['report_id'], report.id)
        box = report.block_ids
        self.assertEqual((box.type, box.res_model, box.view_type, box.width), ('view', 'res.partner', 'graph', 2))
        self.assertNotIn('search_default_x', box.context)
        data = box._data()
        self.assertEqual(data['chart']['kind'], 'pie')
        self.assertIn('<svg', report.board_data['boxes'][0]['html'])
        created = self.make_jsonrpc_request('/report_studio/add_view', {
            'action_id': action.id, 'context_to_save': {}, 'domain': [], 'view_mode': 'list', 'name': 'Contacts',
            'new_report': 'From the contacts list'})
        new = self.env['report.studio.report'].browse(created['report_id'])
        self.assertEqual(new.name, 'From the contacts list')
        self.assertTrue(new.block_ids._data()['columns'])
