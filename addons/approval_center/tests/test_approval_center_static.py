"""Database-free checks for the Approval Center module definition."""

import ast
import csv
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


class TestApprovalCenterStatic(unittest.TestCase):
    def test_manifest_identity_is_complete(self):
        manifest = ast.literal_eval((MODULE / '__manifest__.py').read_text())

        self.assertEqual(manifest['name'], 'Approval Center')
        self.assertEqual(manifest['summary'], 'Review, approve, and audit supervised business actions')
        self.assertEqual(manifest['icon'], '/approval_center/static/description/icon.svg')
        self.assertTrue(manifest['application'])
        self.assertLessEqual({'base', 'hr', 'mail'}, set(manifest['depends']))
        self.assertIn('data/approval_center_data.xml', manifest['data'])
        self.assertIn('approval_center/static/src/scss/approval_center.scss', manifest['assets']['web.assets_backend'])

    def test_security_access_has_core_models_and_groups(self):
        with (MODULE / 'security/ir.access.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))

        models = {row['model_id'] for row in rows}
        groups = {row['group_id/id'] for row in rows}
        self.assertLessEqual({
            'approval.center.request',
            'approval.center.policy',
            'approval.center.approver',
            'approval.center.audit',
        }, models)
        self.assertLessEqual({
            'approval_center.group_approval_center_user',
            'approval_center.group_approval_center_approver',
            'approval_center.group_approval_center_manager',
        }, groups)
        rows_by_id = {row['id']: row for row in rows}
        self.assertEqual(rows_by_id['access_approval_center_approver_user']['operation'], 'r')
        self.assertEqual(rows_by_id['access_approval_center_approver_request_user']['operation'], 'cud')
        self.assertIn("request_id.requester_id", rows_by_id['access_approval_center_approver_request_user']['domain'])
        self.assertEqual(rows_by_id['access_approval_center_approver_approver']['operation'], 'ru')
        self.assertIn("user_id", rows_by_id['access_approval_center_approver_approver']['domain'])

    def test_views_expose_approval_type_dashboard_and_requested_views(self):
        root = ET.parse(MODULE / 'views/approval_center_views.xml').getroot()
        xml = ET.tostring(root, encoding='unicode')

        self.assertIn('action_approval_center_requests', xml)
        self.assertIn('action_approval_center_types', xml)
        self.assertIn('action_approval_center_dashboard', xml)
        self.assertIn('action_approval_center_audits', xml)
        self.assertIn('menu_approval_center_root', xml)
        self.assertIn('menu_approval_center_configuration', xml)
        self.assertIn('menu_approval_center_types', xml)
        self.assertIn('o_approval_center_list', xml)
        self.assertIn('web_icon="approval_center,static/description/icon.svg"', xml)
        self.assertIn('action_approve', xml)
        self.assertIn('action_refuse', xml)
        self.assertIn('Approver(s)', xml)
        self.assertIn('has_document', xml)
        self.assertIn('has_location', xml)
        self.assertIn('options="{\'horizontal\': true}"', xml)
        self.assertIn("'size': [32, 32]", xml)
        self.assertIn('selected_approver_user_ids', xml)
        self.assertIn("domain=\"[('id', 'not in', parent.selected_approver_user_ids)]\"", xml)
        self.assertIn('approval_center_type_view_search', xml)
        self.assertIn('width="150px"', xml)
        self.assertIn('width="170px"', xml)
        self.assertIn('width="190px"', xml)
        self.assertIn('name="archived"', xml)
        self.assertIn('active_test', xml)
        self.assertIn('editable="bottom"', xml)
        self.assertIn('approval_minimum', xml)
        self.assertIn('ir.actions.report', xml)
        self.assertIn('print_report_name', xml)
        self.assertNotIn('report_file', xml)
        self.assertIn('view_mode">kanban,list,form', xml)
        self.assertNotIn('string="Execute Action"', xml)
        request_form = next(
            record for record in root.findall('record')
            if record.attrib.get('id') == 'approval_center_request_view_form'
        )
        request_form_xml = ET.tostring(request_form, encoding='unicode')
        self.assertNotIn('name="target_model"', request_form_xml)
        self.assertNotIn('name="target_res_id"', request_form_xml)
        for field_name in [
            'document_ids',
            'partner_id',
            'date',
            'date_start',
            'date_end',
            'item',
            'quantity',
            'amount',
            'reference',
            'payment',
            'location',
        ]:
            self.assertIn(f'name="{field_name}"', request_form_xml)
        self.assertIn("invisible=\"not policy_id or has_document == 'no'\"", request_form_xml)
        self.assertIn("required=\"has_document == 'required'\"", request_form_xml)
        self.assertIn("invisible=\"not policy_id or has_location == 'no'\"", request_form_xml)
        self.assertIn("required=\"has_location == 'required'\"", request_form_xml)
        self.assertIn('class="text-muted me-1">From:', request_form_xml)
        self.assertIn('class="text-muted ms-3 me-1">to:', request_form_xml)
        self.assertIn('name="date_start" class="oe_inline"', request_form_xml)
        self.assertIn('name="date_end" class="oe_inline"', request_form_xml)
        self.assertIn('statusbar_visible="to_submit,submitted,approved,refused"', request_form_xml)
        type_kanban = next(
            record for record in root.findall('record')
            if record.attrib.get('id') == 'approval_center_type_view_kanban'
        )
        type_kanban_xml = ET.tostring(type_kanban, encoding='unicode')
        self.assertIn('create="0"', type_kanban_xml)
        self.assertIn('can_open="0"', type_kanban_xml)
        self.assertIn('min-height: 120px', type_kanban_xml)
        self.assertIn("'size': [52, 52]", type_kanban_xml)
        self.assertIn('btn-sm', type_kanban_xml)
        self.assertNotIn('type="archive"', type_kanban_xml)

    def test_seed_data_has_default_approval_types(self):
        root = ET.parse(MODULE / 'data/approval_center_data.xml').getroot()
        xml = ET.tostring(root, encoding='unicode')

        for approval_type in [
            'Business Trip',
            'Borrow Items',
            'General Approval',
            'Contract Approval',
            'Payment Application',
            'Car Rental Application',
            'Job Referral Award',
            'Procurement',
        ]:
            self.assertIn(approval_type, xml)
        self.assertIn('approval_type_business_trip.svg', xml)
        self.assertIn('approval_type_procurement.svg', xml)

    def test_approver_model_prevents_duplicates(self):
        source = (MODULE / 'models/approval_center_approver.py').read_text()

        self.assertIn('_check_unique_approver_scope', source)
        self.assertIn('same approver cannot be added twice to the same approval type', source)
        self.assertIn('same approver cannot be added twice to the same approval request', source)

    def test_selected_approvers_are_exposed_for_dropdown_domains(self):
        policy_source = (MODULE / 'models/approval_center_policy.py').read_text()
        request_source = (MODULE / 'models/approval_center_request.py').read_text()

        self.assertIn('selected_approver_user_ids', policy_source)
        self.assertIn('_compute_selected_approver_user_ids', policy_source)
        self.assertIn('selected_approver_user_ids', request_source)
        self.assertIn('_compute_selected_approver_user_ids', request_source)
        self.assertIn('def default_get', request_source)
        self.assertIn('_get_approval_type_approver_commands', request_source)

    def test_request_model_has_policy_driven_optional_fields(self):
        request_source = (MODULE / 'models/approval_center_request.py').read_text()

        for field_name in [
            'has_document',
            'has_partner',
            'has_date',
            'has_period',
            'has_items',
            'has_quantity',
            'has_amount',
            'has_reference',
            'has_payment',
            'has_location',
            'document_ids',
            'partner_id',
            'date',
            'item',
            'quantity',
            'amount',
            'reference',
            'payment',
            'location',
        ]:
            self.assertIn(field_name, request_source)
        self.assertIn('_check_required_fields', request_source)

    def test_review_actions_complete_mail_activities_after_submission(self):
        source = (MODULE / 'models/approval_center_request.py').read_text()

        self.assertIn('activity_schedule', source)
        self.assertIn("summary=_('Review approval request: %s') % self.name", source)
        self.assertIn("note=_('Review approval request: %s') % self.name", source)
        self.assertIn('_notify_approvers', source)
        self.assertIn('message_notify(', source)
        self.assertIn('partner_ids=partner_ids', source)
        self.assertIn('mail_notify_force_send=True', source)
        self.assertIn('force_send=True', source)
        self.assertNotIn('_clear_review_activities', source)
        self.assertNotIn("self.env['mail.activity']", source)
        self.assertNotIn('activity_unlink(', source)
        self.assertEqual(source.count("activity_feedback(['approval_center.mail_act_approval_review'])"), 3)

    def test_calendar_user_unlink_uses_sudo_when_deleting_users(self):
        source = (ROOT / 'addons/calendar/models/res_users.py').read_text()

        self.assertIn('self.calendar_user_ids.sudo().unlink()', source)

    def test_icon_is_custom_svg(self):
        icon = (MODULE / 'static/description/icon.svg').read_text()

        self.assertIn('<svg', icon)
        self.assertIn('viewBox="0 0 50 50"', icon)
        self.assertIn('#1AD3BB', icon)
        self.assertIn('#005E7A', icon)

    def test_list_handle_alignment_is_scoped(self):
        scss = (MODULE / 'static/src/scss/approval_center.scss').read_text()

        self.assertIn('.o_approval_center_list', scss)
        self.assertIn('.o_data_cell.cursor-pointer:has(.o_field_handle)', scss)
        self.assertIn('align-content: center', scss)


if __name__ == '__main__':
    unittest.main()
