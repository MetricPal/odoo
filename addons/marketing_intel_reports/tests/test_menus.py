from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReportMenus(TransactionCase):

    def test_reports_section_has_four_pages_and_no_page_of_its_own(self):
        section = self.env.ref('marketing_intel_reports.menu_reports')
        self.assertEqual(section.parent_id, self.env.ref('marketing_intel.menu_insights'))
        self.assertFalse(section.action, 'the Reports section is a heading, not a page')
        self.assertEqual(section.child_id.sorted('sequence').mapped('name'),
                         ['Executive overview', 'Channel performance', 'Funnel and attribution', 'Audience'])
        for page in section.child_id:
            self.assertEqual(page.action.type, 'ir.actions.client')
            self.assertIn(page.action.tag, ('marketing_intel_reports.page', 'marketing_intel_reports.executive'))
