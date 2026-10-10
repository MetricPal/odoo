from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.addons.workflow_center.models.workflow import internal
from odoo.addons.workflow_center.models.execution import DeliveryUncertain, webhook_target


@tagged('post_install', '-at_install')
class TestWorkflows(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env.ref('base.user_admin')
        cls.env = cls.env(user=cls.manager)
        cls.partner = cls.env['res.partner'].create({'name': 'Workflow test customer'})
        cls.model = cls.env['ir.model']._get('res.partner')

    def test_workflows_is_an_administrator_app(self):
        menu = self.env.ref('workflow_center.menu_workflows')
        self.assertFalse(menu.parent_id)
        self.assertEqual(menu.action, self.env.ref('workflow_center.action_workflow_templates'))
        self.assertEqual(menu.web_icon, 'workflow_center,static/description/icon.svg')
        self.assertTrue(menu.web_icon_data)
        self.assertEqual(menu.group_ids, self.env.ref('base.group_system'))
        self.assertIn(menu, self.env['ir.ui.menu'].get_user_roots())
        user = new_test_user(self.env, login='workflow_app_user', groups='base.group_user')
        self.assertNotIn(menu, self.env['ir.ui.menu'].with_user(user).get_user_roots())
        module = self.env['ir.module.module'].search([('name', '=', 'workflow_center')])
        self.assertTrue(module.application)
        sections = menu.child_id.sorted('sequence')
        self.assertEqual(sections.mapped('name'), ['My workflows', 'Run history'])
        self.assertTrue(all(section.group_ids == menu.group_ids for section in sections))
        self.assertEqual(sections[0].action, self.env.ref('workflow_center.action_workflow_library'))
        self.assertEqual(sections[1].action, self.env.ref('workflow_center.action_run_history'))
        self.assertFalse(self.env.ref('workflow_center.menu_workflows_approvals', raise_if_not_found=False))
        self.assertFalse(self.env.ref('workflow_center.action_workflow_approvals', raise_if_not_found=False))

    def test_run_history_native_action_and_navigation(self):
        action = self.env.ref('workflow_center.action_run_history')
        self.assertEqual(action.res_model, 'workflow.run')
        self.assertEqual(action.view_mode, 'list,kanban,form')
        self.assertEqual(action.search_view_id, self.env.ref('workflow_center.run_search'))
        self.assertEqual(action.limit, 80)
        flow = self.flow()
        run = internal(self.env['workflow.run']).create({
            'workflow_id': flow.id, 'name': self.partner.display_name,
            'record_id': self.partner.id, 'revision': flow.revision, 'is_test': True,
        })
        result = run.action_open_workflow()
        self.assertEqual(result['params']['workflow_id'], flow.id)
        self.assertEqual(result['tag'], 'workflow_center.builder')
        user = new_test_user(self.env, login='workflow_run_reader', groups='base.group_user')
        with self.assertRaises(AccessError):
            run.with_user(user).action_open_workflow()

    def test_run_status_groups_include_empty_columns_in_order(self):
        flow = self.flow()
        run = internal(self.env['workflow.run']).create({
            'workflow_id': flow.id, 'name': self.partner.display_name,
            'record_id': self.partner.id, 'revision': flow.revision,
            'is_test': True, 'state': 'done',
        })
        model = self.env['workflow.run'].with_context(read_group_expand=True)
        for domain, counts in [([('id', '=', run.id)], [0, 0, 0, 1, 0]),
                               ([('id', '=', 0)], [0, 0, 0, 0, 0])]:
            groups = model.formatted_read_group(domain, ['state'], ['__count'])
            self.assertEqual([group['state'] for group in groups],
                             ['running', 'waiting', 'failed', 'done', 'stopped'])
            self.assertEqual([group['__count'] for group in groups], counts)

    def test_workflow_status_groups_include_empty_columns_in_order(self):
        flow = self.flow()
        model = self.env['workflow.definition'].with_context(read_group_expand=True)
        for domain, counts in [([('id', '=', flow.id)], [1, 0, 0]),
                               ([('id', '=', 0)], [0, 0, 0])]:
            groups = model.formatted_read_group(domain, ['state'], ['__count'])
            self.assertEqual([group['state'] for group in groups], ['draft', 'active', 'paused'])
            self.assertEqual([group['__count'] for group in groups], counts)

    def test_library_views_and_guarded_status(self):
        from lxml import etree
        action = self.env.ref('workflow_center.action_workflow_library')
        self.assertEqual(action.res_model, 'workflow.definition')
        self.assertEqual(action.view_mode, 'list,kanban,form')
        for view_type in ('list', 'kanban'):
            view = self.env.ref('workflow_center.workflow_' + view_type)
            arch = etree.fromstring(view.arch_db)
            self.assertEqual(arch.get('action'), 'action_open_builder')
            self.assertEqual(arch.get('type'), 'object')
            if view_type == 'kanban':
                self.assertEqual(arch.get('on_create'), 'workflow_center.action_new_workflow')
                self.assertEqual(arch.get('records_draggable'), 'false')
                self.assertEqual(arch.get('groups_draggable'), 'false')
        flow = self.flow()
        result = flow.action_open_builder()
        self.assertEqual(result['params']['workflow_id'], flow.id)
        self.assertEqual(result['tag'], 'workflow_center.builder')
        for state in ('active', 'paused', 'draft'):
            with self.assertRaises(AccessError):
                flow.write({'state': state})
        self.assertEqual(flow.state, 'draft')
        user = new_test_user(self.env, login='workflow_library_user', groups='base.group_user')
        with self.assertRaises(AccessError):
            flow.with_user(user).action_open_builder()

    def flow(self, **values):
        return self.env['workflow.definition'].create({
            'name': 'Customer follow-up', 'model_id': self.model.id, **values,
        })

    def step(self, flow, kind='action', **values):
        return self.env['workflow.step'].create({
            'workflow_id': flow.id, 'name': 'Follow-up', 'kind': kind,
            'sequence': len(flow.step_ids) * 10, **values,
        })

    def action(self, name='Set reference', **values):
        return self.env['ir.actions.server'].create({
            'name': name, 'model_id': self.model.id, 'state': 'object_write',
            'update_path': 'ref', 'value': 'followed-up', **values,
        })

    def preview(self, flow, record=None):
        return self.env['workflow.test'].create({
            'workflow_id': flow.id, 'record_id': (record or self.partner).id,
        }).action_start()

    def activate(self, flow):
        self.preview(flow)
        flow.action_activate()

    def execute_flow(self, flow, record=None):
        flow._trigger_records(record or self.partner)
        run = flow.run_ids.filtered(lambda r: not r.is_test)[:1]
        if run:
            run._advance()
        return run

    def test_preview_changes_no_business_data_and_activation_is_explicit(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id)
        with self.assertRaises(UserError):
            flow.action_activate()
        self.preview(flow)
        self.assertFalse(self.partner.ref)
        self.assertEqual(flow.state, 'draft')
        flow.action_activate()
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'followed-up')
        self.assertEqual(flow.approved_by, self.manager)

    def test_branch_and_wait_resume_without_repeating_action(self):
        flow = self.flow()
        branch = self.step(flow, 'branch', domain="[('ref', '=', 'paid')]")
        self.step(flow, action_id=self.action(value='thank-you').id, end=True)
        wait = self.step(flow, 'wait', wait_hours=1)
        self.step(flow, action_id=self.action(value='call-needed').id)
        branch.false_id = wait
        self.activate(flow)
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'waiting')
        self.assertFalse(self.partner.ref)
        run._set(wake_at=fields.Datetime.now() - timedelta(seconds=1))
        run._advance()
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'call-needed')
        self.assertEqual(len(run.log_ids.filtered(lambda l: l.message == 'Action completed.')), 1)

    def test_permissions_and_company_isolation(self):
        user = new_test_user(self.env, login='workflow_staff', groups='base.group_user')
        flow = self.flow()
        with self.assertRaises(AccessError):
            flow.with_user(user).action_activate()
        with self.assertRaises(AccessError):
            self.env['workflow.definition'].with_user(user).home_data()
        with self.assertRaises(AccessError):
            flow.write({'state': 'active'})
        with self.assertRaises(AccessError):
            self.env['workflow.run'].create({'workflow_id': flow.id, 'record_id': self.partner.id,
                                             'name': 'Forged', 'revision': 1})
        company = self.env['res.company'].create({'name': 'Separate workflow company'})
        other = self.env['res.partner'].sudo().create({'name': 'Other company', 'company_id': company.id})
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        with self.assertRaises(AccessError):
            self.execute_flow(flow, other)
        self.assertFalse(other.ref)

    def test_configuration_change_requires_retest_and_stops_runtime(self):
        flow = self.flow()
        action = self.action()
        self.step(flow, action_id=action.id)
        self.preview(flow)
        action.value = 'changed'
        with self.assertRaises(UserError):
            flow.action_activate()
        self.activate(flow)
        action.value = 'tampered'
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'failed')
        self.assertFalse(self.partner.ref)
        with self.assertRaises(UserError):
            flow.step_ids.write({'name': 'Changed'})

    def test_native_create_trigger(self):
        flow = self.flow(trigger='create', domain="[('name', '=', 'Triggered customer')]")
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        partner = self.env['res.partner'].create({'name': 'Triggered customer'})
        self.assertFalse(partner.ref)
        flow.run_ids.filtered(lambda r: not r.is_test)._advance()
        self.assertEqual(partner.ref, 'followed-up')
        self.assertEqual(flow.run_ids.filtered(lambda r: not r.is_test).state, 'done')
        flow.action_pause()
        other = self.env['res.partner'].create({'name': 'Triggered customer'})
        self.assertFalse(other.ref)

    def test_failure_retry_and_skip_keep_history(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        with patch.object(type(self.env['workflow.run']), '_execute', side_effect=UserError('Synthetic failure')):
            run = self.execute_flow(flow)
        self.assertEqual(run.state, 'failed')
        self.assertFalse(self.partner.ref)
        run.action_retry()
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'followed-up')
        self.assertTrue(run.log_ids.filtered(lambda l: l.state == 'failed'))
        with self.assertRaises(AccessError):
            run.log_ids[:1].write({'message': 'Forged'})

    def test_uncertain_delivery_never_automatically_retries(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id, on_error='retry')
        self.activate(flow)
        with patch.object(type(self.env['workflow.run']), '_execute', side_effect=DeliveryUncertain('HTTP 503')):
            run = self.execute_flow(flow)
        self.assertEqual(run.state, 'failed')
        self.assertTrue(run.delivery_unknown)
        with self.assertRaises(UserError):
            run.action_retry()
        run.action_retry_confirmed()
        self.assertEqual(run.state, 'done', run.error)

    def test_optional_approval_waits_for_real_decision(self):
        approver = new_test_user(self.env, login='workflow_approver',
                                 groups='approval_center.group_approval_center_approver')
        policy = self.env['approval.center.policy'].create({
            'name': 'Workflow review', 'approver_ids': [fields.Command.create({'user_id': approver.id})],
        })
        flow = self.flow()
        self.step(flow, 'approval', policy_id=policy.id)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'waiting')
        run._advance()
        self.assertFalse(self.partner.ref)
        run.approval_id.with_user(approver).action_approve()
        run._advance()
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'followed-up')

    def test_invalid_graph_and_chat_cannot_activate(self):
        flow = self.flow()
        a = self.step(flow)
        b = self.step(flow)
        b.next_id = a
        self.assertTrue(any('cycle' in issue for issue in flow._validate()))
        b.next_id = False
        a.action_type = 'chat'
        self.assertTrue(any('provider' in issue for issue in flow._validate()))

    def test_insertion_is_after_selected_step(self):
        flow = self.flow()
        first = self.step(flow, name='First')
        last = self.step(flow, name='Last')
        middle = flow.add_step('wait', after_id=first.id)
        self.assertEqual(flow.step_ids.sorted('sequence').ids, [first.id, middle, last.id])

    def test_template_overview_native_views(self):
        action = self.env.ref('workflow_center.action_workflow_templates')
        self.assertEqual(action.view_mode, 'kanban,list')
        self.assertEqual(action.res_model, 'workflow.template')
        self.assertEqual(action.search_view_id, self.env.ref('workflow_center.template_search'))
        template = self.env['workflow.template'].search([('key', '=', 'onboarding')])
        self.assertTrue(template.available)
        result = template.action_start()
        draft = self.env['workflow.definition'].browse(result['params']['workflow_id'])
        self.assertEqual(draft.state, 'draft')
        self.assertEqual(result['tag'], 'workflow_center.builder')

    def test_template_search_catalog_is_read_only(self):
        templates = self.env['workflow.template']
        recipes = self.env['workflow.definition'].home_data()['templates']
        categories = templates.search_panel_select_range('app', enable_counters=True, expand=True)['values']
        self.assertEqual({item['id'] for item in categories}, {item['app'] for item in recipes})
        for item in categories:
            self.assertEqual(item['__count'], sum(recipe['app'] == item['id'] for recipe in recipes))

        self.assertEqual(templates.search([]).mapped('key'), [item['key'] for item in recipes])
        reminders = templates.search([('category', '=', 'Reminders')])
        self.assertEqual(set(reminders.mapped('key')),
                         {item['key'] for item in recipes if item['category'] == 'Reminders'})
        with self.assertRaises(AccessError):
            reminders.write({'name': 'Changed template'})
        with self.assertRaises(AccessError):
            templates.create({'name': 'Unapproved recipe'})
        with self.assertRaises(AccessError):
            reminders.unlink()
        user = new_test_user(self.env, login='template_catalog_staff', groups='base.group_user')
        with self.assertRaises(AccessError):
            templates.with_user(user).search_read([], ['name'])

    def test_template_catalog_and_onboarding_shape(self):
        self.assertEqual(len(self.env['workflow.definition'].home_data()['templates']), 11)
        flow = self.env['workflow.definition'].browse(self.env['workflow.definition'].from_template('onboarding'))
        self.assertNotIn('branch', flow.step_ids.mapped('kind'))
        self.assertEqual(flow.state, 'draft')
        self.assertTrue(flow._validate())

    def test_webhook_allowlist_blocks_local_and_unapproved_hosts(self):
        with self.assertRaises(UserError):
            webhook_target('http://localhost/test')
        with patch.dict('os.environ', {'WORKFLOW_WEBHOOK_HOSTS': 'example.com'}):
            with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 443))]):
                with self.assertRaises(UserError):
                    webhook_target('https://example.com/test')

    def test_schedule_and_pause(self):
        flow = self.flow(trigger='schedule', domain=f"[('id', '=', {self.partner.id})]")
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        internal(flow).write({'next_run': fields.Datetime.now() - timedelta(seconds=1)})
        self.env['workflow.run']._cron_advance()
        self.assertFalse(self.partner.ref)
        self.env['workflow.run']._cron_advance()
        self.assertEqual(self.partner.ref, 'followed-up')
        self.assertEqual(len(flow.run_ids.filtered(lambda r: not r.is_test)), 1)
        self.env['workflow.run']._cron_advance()
        self.assertEqual(len(flow.run_ids.filtered(lambda r: not r.is_test)), 1)
        flow.action_pause()
        self.partner.ref = False
        internal(flow).write({'next_run': fields.Datetime.now() - timedelta(seconds=1)})
        self.env['workflow.run']._cron_advance()
        self.assertFalse(self.partner.ref)

    def test_for_each_related_record(self):
        flow = self.flow()
        children = self.env['res.partner'].create([
            {'name': 'Child one', 'parent_id': self.partner.id},
            {'name': 'Child two', 'parent_id': self.partner.id},
        ])
        self.step(flow, 'foreach',
                  relation_field_id=self.env['ir.model.fields']._get('res.partner', 'child_ids').id,
                  action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(children.mapped('ref'), ['followed-up', 'followed-up'])
        self.assertFalse(self.partner.ref)

    def test_execution_does_not_inherit_automation_superuser(self):
        user = new_test_user(self.env, login='workflow_executor', groups='base.group_user,base.group_partner_manager')
        flow = self.flow(user_id=user.id)
        action = self.action()
        self.step(flow, action_id=action.id)
        self.activate(flow)
        # Deny the actual target write, while allowing the workflow metadata.
        self.env['ir.access'].create({
            'name': 'Deny test target updates', 'model_id': self.model.id,
            'operation': 'u', 'domain': f"[('id', '!=', {self.partner.id})]",
        })
        run = self.execute_flow(flow.sudo())
        self.assertEqual(run.state, 'failed')
        self.assertFalse(self.partner.ref)

    def test_incoming_webhook_queues_matching_record(self):
        flow = self.flow(trigger='webhook', domain=f"[('id', '=', {self.partner.id})]")
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        flow.automation_id._execute_webhook({'_id': self.partner.id})
        self.assertFalse(self.partner.ref)
        run = flow.run_ids.filtered(lambda r: not r.is_test)
        self.assertEqual(len(run), 1)
        run._advance()
        self.assertEqual(self.partner.ref, 'followed-up')

    def test_skip_and_stop_controls(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id)
        self.step(flow, 'wait', wait_hours=10)
        self.activate(flow)
        with patch.object(type(self.env['workflow.run']), '_execute', side_effect=UserError('Synthetic failure')):
            run = self.execute_flow(flow)
        run.action_skip()
        self.assertEqual(run.state, 'waiting')
        self.assertFalse(self.partner.ref)
        run.action_stop()
        run._advance()
        self.assertEqual(run.state, 'stopped')

    def test_approval_rejection_stops_the_run(self):
        approver = new_test_user(self.env, login='workflow_refuser',
                                 groups='approval_center.group_approval_center_approver')
        policy = self.env['approval.center.policy'].create({
            'name': 'Reject workflow review', 'approver_ids': [fields.Command.create({'user_id': approver.id})],
        })
        flow = self.flow()
        self.step(flow, 'approval', policy_id=policy.id)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        run.approval_id.with_user(approver).action_refuse()
        self.env['workflow.run']._cron_advance()
        self.assertEqual(run.state, 'stopped')
        self.assertFalse(self.partner.ref)

    def test_tracked_webhook_records_failure_and_reuses_delivery_key(self):
        action = self.action(state='webhook', webhook_url='https://example.com/events')
        flow = self.flow()
        self.step(flow, action_type='webhook', action_id=action.id)
        from unittest.mock import MagicMock
        pool = MagicMock()
        response = MagicMock(status=503)
        pool.request.return_value = response
        with patch.dict('os.environ', {'WORKFLOW_WEBHOOK_HOSTS': 'example.com'}), patch(
            'socket.getaddrinfo', return_value=[(None, None, None, None, ('93.184.216.34', 443))]
        ), patch('urllib3.HTTPSConnectionPool', return_value=pool):
            self.activate(flow)
            run = self.execute_flow(flow)
            self.assertEqual(run.state, 'failed')
            self.assertIn('503', run.error)
            self.assertTrue(run.delivery_unknown)
            key = pool.request.call_args.kwargs['headers']['Idempotency-Key']
            self.assertFalse(pool.request.call_args.kwargs['redirect'])
            response.status = 204
            run.action_retry_confirmed()
            self.assertEqual(run.state, 'done', run.error)
            self.assertEqual(pool.request.call_args.kwargs['headers']['Idempotency-Key'], key)

    def test_date_trigger_uses_native_odoo_date_automation(self):
        flow = self.flow(trigger='date',
                         date_field_id=self.env['ir.model.fields']._get('res.partner', 'create_date').id,
                         offset_days=7)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        self.assertEqual(flow.automation_id.trigger, 'on_time')
        self.assertEqual(flow.automation_id.trg_date_range, 7)
        self.assertEqual(flow.automation_id.trg_date_range_mode, 'after')
        self.assertEqual(flow.automation_id.trg_date_range_type, 'day')

    def test_portal_cannot_read_workflows_or_run_history(self):
        portal = new_test_user(self.env, login='workflow_portal', groups='base.group_portal')
        flow = self.flow()
        with self.assertRaises(AccessError):
            flow.with_user(portal).read(['name'])
        with self.assertRaises(AccessError):
            self.env['workflow.run'].with_user(portal).search([])

    def test_preview_dialog_uses_execution_user_access(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id)
        company = self.env['res.company'].create({'name': 'Preview company'})
        other = self.env['res.partner'].sudo().create({'name': 'Private preview', 'company_id': company.id})
        with self.assertRaises(AccessError):
            self.preview(flow, other)
        self.assertFalse(flow.tested_revision)

    def test_approval_cannot_be_forged_or_self_approved(self):
        flow = self.flow()
        other = new_test_user(self.env, login='workflow_other', groups='approval_center.group_approval_center_approver')
        policy = self.env['approval.center.policy'].create({
            'name': 'Self review denied', 'approver_ids': [
                fields.Command.create({'user_id': self.manager.id}),
                fields.Command.create({'user_id': other.id}),
            ],
        })
        self.step(flow, 'approval', policy_id=policy.id)
        self.activate(flow)
        run = self.execute_flow(flow)
        request = run.approval_id
        with self.assertRaises(AccessError):
            request.write({'state': 'approved'})
        with self.assertRaises(AccessError):
            request.approver_ids.write({'status': 'approved'})
        with self.assertRaises(AccessError):
            request.action_approve()
        run._advance()
        self.assertEqual(run.state, 'waiting')

    def test_internal_execution_user_can_perform_permitted_action(self):
        user = new_test_user(self.env, login='workflow_permitted_executor', groups='base.group_user,base.group_partner_manager')
        flow = self.flow(user_id=user.id)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'done', run.error)
        self.assertEqual(self.partner.ref, 'followed-up')

    def test_create_record_maps_source_fields_and_fixed_values(self):
        flow = self.flow()
        self.partner.email = 'synthetic@example.invalid'
        step = self.step(flow, action_type='object_create', create_model_id=self.model.id)
        self.env['workflow.value'].create([
            {'step_id': step.id, 'field_id': self.env['ir.model.fields']._get('res.partner', 'name').id,
             'source': 'fixed', 'text_value': 'Created by a reviewed workflow'},
            {'step_id': step.id, 'field_id': self.env['ir.model.fields']._get('res.partner', 'email').id,
             'source': 'field', 'source_field_id': self.env['ir.model.fields']._get('res.partner', 'email').id},
            {'step_id': step.id, 'field_id': self.env['ir.model.fields']._get('res.partner', 'parent_id').id,
             'source': 'record'},
        ])
        self.activate(flow)
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Created by a reviewed workflow')]))
        run = self.execute_flow(flow)
        self.assertEqual(run.state, 'done', run.error)
        created = self.env['res.partner'].search([('name', '=', 'Created by a reviewed workflow')])
        self.assertEqual(created.email, self.partner.email)
        self.assertEqual(created.parent_id, self.partner)
        with self.assertRaises(UserError):
            step.value_ids[:1].write({'text_value': 'Changed without review'})

    def test_approval_required_reviewers_and_order_are_frozen(self):
        first = new_test_user(self.env, login='workflow_first', groups='approval_center.group_approval_center_approver')
        second = new_test_user(self.env, login='workflow_second', groups='approval_center.group_approval_center_approver')
        policy = self.env['approval.center.policy'].create({
            'name': 'Ordered workflow review', 'approval_minimum': 2, 'approver_sequence': True,
            'approver_ids': [
                fields.Command.create({'user_id': first.id, 'sequence': 1, 'required': True}),
                fields.Command.create({'user_id': second.id, 'sequence': 2, 'required': True}),
            ],
        })
        flow = self.flow()
        self.step(flow, 'approval', policy_id=policy.id)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        request = run.approval_id
        with self.assertRaises(UserError):
            request.with_user(second).action_approve()
        policy.write({'approval_minimum': 1, 'approver_sequence': False})
        request.with_user(first).action_approve()
        run._advance()
        self.assertEqual(run.state, 'waiting')
        request.with_user(second).action_approve()
        run._advance()
        self.assertEqual(run.state, 'done', run.error)

    def test_insert_after_end_keeps_new_step_in_the_path(self):
        flow = self.flow()
        end = self.step(flow, 'wait', end=True)
        added = self.env['workflow.step'].browse(flow.add_step('wait', after_id=end.id))
        self.assertFalse(end.end)
        self.assertEqual(end._next(), added)
        self.assertTrue(added.end)

    def test_record_change_invalidates_pending_approval(self):
        approver = new_test_user(self.env, login='workflow_changed_record', groups='approval_center.group_approval_center_approver')
        policy = self.env['approval.center.policy'].create({
            'name': 'Review record snapshot', 'approver_ids': [fields.Command.create({'user_id': approver.id})],
        })
        flow = self.flow()
        self.step(flow, 'approval', policy_id=policy.id)
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        run = self.execute_flow(flow)
        self.partner.ref = 'Changed during review'
        run.approval_id.with_user(approver).action_approve()
        run._advance()
        self.assertEqual(run.state, 'failed')
        self.assertIn('changed while approval', run.error)
        self.assertEqual(self.partner.ref, 'Changed during review')

    def test_manual_workflow_binds_to_source_action_menu(self):
        flow = self.flow()
        self.step(flow, action_id=self.action().id)
        self.activate(flow)
        action = flow.manual_action_id
        self.assertEqual(action.binding_model_id, self.model)
        operator = new_test_user(self.env, login='workflow_manual_operator', groups='base.group_user,base.group_partner_manager')
        action.with_user(operator).with_context(active_model='res.partner', active_id=self.partner.id,
                            active_ids=self.partner.ids).run()
        self.assertFalse(self.partner.ref)
        run = flow.run_ids.filtered(lambda r: not r.is_test)
        run._advance()
        self.assertEqual(self.partner.ref, 'followed-up')
        flow.action_pause()
        self.assertFalse(action.binding_model_id)
