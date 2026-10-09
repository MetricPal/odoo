from unittest.mock import patch
from odoo.tests.common import ChromeBrowser
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestWorkflowUI(HttpCase):
    def test_home_and_builder(self):
        original = ChromeBrowser._handle_console
        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value', '').startswith('workflow_capture_'):
                browser.take_screenshot(prefix=args[0]['value'] + '_')
            return original(browser, type, args=args, **kwargs)
        self.patch(ChromeBrowser, '_handle_console', capture)
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Workflow UI did not reach expected state: ' + document.body.innerText.slice(-1500));
                };
                await waitFor(() => document.querySelectorAll('.wf_template').length === 11);
                if (document.querySelector('.wf_nav')) throw new Error('Duplicate workflow navbar');
                const newButton = document.querySelector('.o_control_panel_main_buttons .o_workflow_button_add');
                if (!newButton || newButton.textContent.trim() !== 'New') throw new Error('Missing native New button');
                newButton.click();
                await waitFor(() => document.querySelector('.modal [name="model_id"]'));
                document.querySelector('.modal [aria-label="Close"]').click();
                await waitFor(() => !document.querySelector('.modal'));
                if (!document.body.innerText.includes('AI drafting is not connected')) throw new Error('Missing honest drafting status');
                console.log('workflow_capture_home');
                await new Promise(resolve => setTimeout(resolve, 300));
                const onboarding = [...document.querySelectorAll('.wf_template')].find(n => n.innerText.includes('New employee onboarding'));
                onboarding.click();
                await waitFor(() => document.querySelectorAll('.wf_node').length === 6);
                if (!document.body.innerText.includes('Before you activate')) throw new Error('Missing setup checks');
                if (!document.querySelector('.wf_header .btn-primary').disabled) throw new Error('Incomplete template can activate');
                console.log('workflow_capture_builder');
                await new Promise(resolve => setTimeout(resolve, 300));
                document.querySelectorAll('.wf_node_select')[1].click();
                await waitFor(() => document.body.innerText.includes('Step settings'));
                const wait = [...document.querySelectorAll('.wf_palette button')].find(n => n.innerText.trim() === 'Wait');
                wait.click();
                await waitFor(() => document.querySelector('.modal'));
                if (document.documentElement.scrollWidth > window.innerWidth + 2) throw new Error('Horizontal page overflow');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_mobile_home_and_builder(self):
        self.browser_size = '390x844'
        self.test_home_and_builder()

    def test_run_history_retry_and_preview_record_picker(self):
        from odoo.exceptions import UserError
        manager = self.env.ref('base.user_admin')
        env = self.env(user=manager)
        partner = env['res.partner'].create({'name': 'Workflow UI customer'})
        model = env['ir.model']._get('res.partner')
        flow = env['workflow.definition'].create({'name': 'UI customer follow-up', 'model_id': model.id})
        action = env['ir.actions.server'].create({
            'name': 'Set customer reference', 'model_id': model.id,
            'state': 'object_write', 'update_path': 'ref', 'value': 'workflow-ui',
        })
        env['workflow.step'].create({'workflow_id': flow.id, 'name': 'Update customer reference',
                                     'action_id': action.id})
        env['workflow.test'].create({'workflow_id': flow.id, 'record_id': partner.id}).action_start()
        flow.action_activate()
        flow._trigger_records(partner)
        run = flow.run_ids.filtered(lambda r: not r.is_test)
        with patch.object(type(run), '_execute', side_effect=UserError('Temporary test failure')):
            run._advance()
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing workflow control: ' + document.body.innerText.slice(-1800));
                };
                await waitFor(() => document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_runs"]'));
                document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_runs"]').click();
                await waitFor(() => document.querySelector('.wf_runs .wf_link'));
                document.querySelector('.wf_runs .wf_link').click();
                await waitFor(() => document.querySelector('.wf_run_controls .btn-primary'));
                if (!document.querySelector('.wf_timeline').innerText.includes('Temporary test failure')) throw new Error('Failure not explained');
                document.querySelector('.wf_run_controls .btn-primary').click();
                await waitFor(() => document.querySelector('.modal-footer .btn-primary'));
                document.querySelector('.modal-footer .btn-primary').click();
                await waitFor(() => document.querySelector('.wf_runs tbody .wf_status.done'));
                document.querySelector('.wf_runs aside .wf_link').click();
                await waitFor(() => document.querySelector('.wf_builder'));
                document.querySelector('.wf_header .btn-outline-primary').click();
                await waitFor(() => document.querySelector('.modal [name="record_id"] input'));
                const input = document.querySelector('.modal [name="record_id"] input');
                input.focus(); input.value = 'Workflow UI customer'; input.dispatchEvent(new Event('input', {bubbles: true}));
                await waitFor(() => [...document.querySelectorAll('.o-autocomplete--dropdown-item')].some(n => n.textContent.includes('Workflow UI customer')));
                [...document.querySelectorAll('.o-autocomplete--dropdown-item')].find(n => n.textContent.includes('Workflow UI customer')).click();
                document.querySelector('.modal button[name="action_start"]').click();
                await waitFor(() => document.querySelectorAll('.modal').length > 1);
                [...document.querySelectorAll('.modal-footer .btn-primary')].at(-1).click();
                await waitFor(() => document.querySelector('.o_list_renderer'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
        partner.invalidate_recordset()
        self.assertEqual(partner.ref, 'workflow-ui')

    def test_branch_paths_and_new_record_mapping_form(self):
        manager = self.env.ref('base.user_admin')
        env = self.env(user=manager)
        model = env['ir.model']._get('res.partner')
        flow = env['workflow.definition'].create({'name': 'Branch and create UI', 'model_id': model.id})
        branch = env['workflow.step'].create({
            'workflow_id': flow.id, 'name': 'Has email?', 'kind': 'branch', 'sequence': 0,
            'domain': "[('email', '!=', False)]",
        })
        env['workflow.step'].create({
            'workflow_id': flow.id, 'name': 'Create follow-up contact', 'sequence': 10,
            'action_type': 'object_create', 'end': True,
        })
        no = env['workflow.step'].create({
            'workflow_id': flow.id, 'name': 'Wait for contact details', 'kind': 'wait',
            'sequence': 20, 'end': True,
        })
        branch.false_id = no
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Missing branch/mapping control: ' + document.body.innerText.slice(-1800));
                };
                const choose = async (input, text) => {
                    input.focus(); input.value = text; input.dispatchEvent(new Event('input', {bubbles: true}));
                    await waitFor(() => [...document.querySelectorAll('.o-autocomplete--dropdown-item')].some(n => (n.textContent.trim() === text || n.textContent.trim() === text + ' (Contact)')));
                    [...document.querySelectorAll('.o-autocomplete--dropdown-item')].find(n => (n.textContent.trim() === text || n.textContent.trim() === text + ' (Contact)')).click();
                };
                await waitFor(() => [...document.querySelectorAll('.wf_link')].some(n => n.textContent === 'Branch and create UI'));
                [...document.querySelectorAll('.wf_link')].find(n => n.textContent === 'Branch and create UI').click();
                await waitFor(() => document.querySelectorAll('.wf_branch_paths > section').length === 2);
                const paths = document.querySelectorAll('.wf_branch_paths > section');
                if (!paths[0].innerText.includes('Create follow-up contact') || !paths[1].innerText.includes('Wait for contact details')) throw new Error('Branch paths are mixed');
                paths[0].querySelector('.wf_node_select').click();
                await waitFor(() => [...document.querySelectorAll('.wf_builder aside button')].some(n => n.textContent === 'Step settings'));
                [...document.querySelectorAll('.wf_builder aside button')].find(n => n.textContent === 'Step settings').click();
                await waitFor(() => document.querySelector('.modal [name="create_model_id"] input'));
                await choose(document.querySelector('.modal [name="create_model_id"] input'), 'Contact');
                await waitFor(() => document.querySelector('.modal [name="value_ids"] .o_field_x2many_list_row_add button'));
                document.querySelector('.modal [name="value_ids"] .o_field_x2many_list_row_add button').click();
                await waitFor(() => document.querySelector('.modal [name="field_id"] input'));
                await choose(document.querySelector('.modal [name="field_id"] input'), 'Name');
                await waitFor(() => document.querySelector('.modal [name="text_value"] input'));
                const text = document.querySelector('.modal [name="text_value"] input');
                text.value = 'UI created record'; text.dispatchEvent(new Event('input', {bubbles: true}));
                [...document.querySelectorAll('.modal-footer button')].find(n => n.textContent.trim() === 'Save & Close').click();
                await waitFor(() => document.querySelectorAll('.modal').length === 1);
                document.querySelector('.modal-footer .btn-primary').click();
                await waitFor(() => !document.querySelector('.modal'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
        self.assertEqual(flow.step_ids.filtered(lambda s: s.action_type == 'object_create').value_ids.text_value,
                         'UI created record')

    def test_navbar_overview_and_run_history(self):
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Workflow navigation did not finish');
                };
                await waitFor(() => document.querySelector('.wf_home'));
                for (const suffix of ['overview', 'runs']) {
                    await waitFor(() => document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_' + suffix + '"]'));
                }
                if (document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_approvals"]')) throw new Error('Unexpected approval shortcut');
                document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_runs"]').click();
                await waitFor(() => document.querySelector('.wf_runs'));
                document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_overview"]').click();
                await waitFor(() => document.querySelector('.wf_home'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
