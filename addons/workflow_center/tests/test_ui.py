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
                if (document.querySelector('.wf_home .wf_link')) throw new Error('Existing workflows still on overview');
                if (document.querySelector('.wf_describe')) throw new Error('Creation panel remains on overview');
                if (document.querySelector('.wf_nav')) throw new Error('Duplicate workflow navbar');
                const newButton = document.querySelector('.o_control_panel_main_buttons .o_workflow_button_add');
                if (!newButton || newButton.textContent.trim() !== 'New') throw new Error('Missing native New button');
                newButton.click();
                await waitFor(() => document.querySelector('.o_form_sheet .o_workflow_starter .wf_describe'));
                if (document.querySelector('.modal') || document.querySelector('.o_kanban_renderer')) throw new Error('New did not open a dedicated page');
                const formNew = document.querySelector('.o_control_panel_main_buttons .o_form_button_create');
                if (!formNew?.nextElementSibling?.classList.contains('o_workflow_open_builder')) throw new Error('Open builder is not immediately after New');
                if (document.querySelector('.o_form_statusbar .o_workflow_open_builder')) throw new Error('Builder button remains below the toolbar');
                if (!document.body.innerText.includes('AI drafting is not connected')) throw new Error('Missing honest drafting status');
                document.querySelector('.o_control_panel .breadcrumb a').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length === 11);
                console.log('workflow_capture_home');
                await new Promise(resolve => setTimeout(resolve, 300));
                const onboarding = [...document.querySelectorAll('.wf_template')].find(n => n.innerText.includes('New employee onboarding'));
                onboarding.click();
                await waitFor(() => document.querySelectorAll('.wf_node').length === 6);
                const workflowTitle = () => document.querySelector('.o_control_panel .o_last_breadcrumb_item')?.textContent.trim();
                await waitFor(() => workflowTitle() === 'New employee onboarding');
                if (document.body.innerText.includes('Before you activate')) throw new Error('Removed checklist remains');
                if (document.querySelector('.wf_header')) throw new Error('Duplicate canvas heading remains');
                if (document.querySelector('.o_control_panel_breadcrumbs_actions .wf_status')?.textContent.trim() !== 'Draft') throw new Error('Workflow status missing beside navbar name');
                const guide = document.querySelector('.wf_builder_guide');
                if (!document.querySelector('.o_control_panel_main_buttons .wf_preview')) throw new Error('Preview missing from native toolbar');
                if (!document.querySelector('.o_search_panel .wf_palette') && !document.querySelector('.o_search_panel.wf_palette')) throw new Error('Step menu missing from search panel');
                if (!guide.closest('.o-mail-Chatter-content')) throw new Error('Guide missing from right content');
                if (!guide.textContent.includes('Every workflow is When → If → Do')) throw new Error('Workflow guide content missing');
                if (!document.querySelector('.o_control_panel .wf_activate').disabled) throw new Error('Incomplete template can activate');
                if (document.querySelector('.o_control_panel .wf_settings')) throw new Error('Duplicate Settings button remains');
                if (!document.querySelector('.wf_trigger')) throw new Error('Workflow starting point missing');
                const handle = document.querySelector('.o_search_panel_resize');
                const panel = document.querySelector('.o_search_panel.wf_palette');
                const width = panel.offsetWidth;
                handle.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, clientX: 200 }));
                document.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 240 }));
                document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, button: 0, clientX: 240 }));
                if (panel.offsetWidth <= width) throw new Error('Step panel did not resize');
                if (document.querySelector('.o-mail-Chatter-content').textContent.includes('Select a step to inspect it.')) throw new Error('Removed hint remains');
                if (document.querySelector('.wf_trigger').classList.contains('is_selected')) throw new Error('Starting point selected initially');
                document.querySelector('.wf_trigger').click();
                await waitFor(() => document.querySelector('.wf_step_inspector [name="trigger"]'));
                if (document.querySelector('.modal')) throw new Error('Starting-point settings opened in a popup');
                if (workflowTitle() !== 'New employee onboarding') throw new Error('Starting-point inspector overwrote workflow name');
                if (!document.querySelector('.wf_trigger').classList.contains('is_selected')) throw new Error('Selected starting point is not highlighted');
                if (!document.querySelector('.wf_inspector_toolbar .o_form_button_save')) throw new Error('Starting-point save not in right-panel toolbar');
                if (document.querySelector('.wf_inspector_actions .vr')) throw new Error('Unnecessary divider on starting-point settings');
                if (document.querySelector('.wf_builder_guide')) throw new Error('Guide remains during trigger editing');
                if (document.querySelector('.wf_step_inspector .o-mail-ChatterContainer')) throw new Error('Nested chatter in inspector');
                document.querySelector('[aria-label="Close step settings"]').click();
                await waitFor(() => !document.querySelector('.wf_step_inspector') && document.querySelector('.wf_builder_guide'));
                for (const button of document.querySelectorAll('.wf_remove_step')) {
                    const style = getComputedStyle(button);
                    if (!button.classList.contains('text-danger') || style.backgroundColor !== 'rgba(0, 0, 0, 0)' || style.borderTopWidth !== '0px') throw new Error('Removal control must have red text without background or border');
                }
                console.log('workflow_capture_builder');
                await new Promise(resolve => setTimeout(resolve, 300));
                document.querySelectorAll('.wf_node_select')[1].click();
                await waitFor(() => document.querySelector('.wf_step_inspector [name="name"] input'));
                if (document.querySelector('.wf_builder_guide')) throw new Error('Guide remains while step selected');
                if (workflowTitle() !== 'New employee onboarding') throw new Error('Step inspector overwrote workflow name');
                const actions = document.querySelector('.wf_inspector_toolbar .wf_inspector_actions');
                if (!actions?.querySelector('.o_form_button_save') || !actions.querySelector('.o_form_button_cancel') || !actions.querySelector('.wf_remove_step')) throw new Error('Missing right-hand inspector actions');
                if (document.querySelector('.o_control_panel .wf_inspector_actions')) throw new Error('Actions remain in main control panel');
                const saveRect = actions.querySelector('.o_form_button_save').getBoundingClientRect();
                if (saveRect.height > 60) throw new Error('Inspector toolbar button is stretched');
                const labels = [...actions.querySelectorAll('button')].map(button => button.textContent.trim());
                if (labels.slice(0, 3).join('|') !== 'Save|Discard|Remove step') throw new Error('Incorrect inspector button order');
                if (!actions.querySelector('.wf_remove_step').classList.contains('btn-secondary')) throw new Error('Remove step is not secondary');
                if (!actions.closest('.o-mail-Chatter-top').querySelector('hr')) throw new Error('Horizontal toolbar divider missing');
                if (document.querySelector('.wf_trigger').classList.contains('is_selected') || document.querySelectorAll('.wf_node.is_selected').length !== 1) throw new Error('Starting point remains selected alongside a step');
                const wait = [...document.querySelectorAll('.wf_palette button')].find(n => n.innerText.trim() === 'Wait');
                if (wait.getAttribute('draggable') !== 'true' || !wait.draggable) throw new Error('Palette item is not natively draggable');
                if (document.querySelector('.wf_palette').textContent.includes('After:')) throw new Error('Old palette hint remains');
                if (!document.querySelector('.wf_palette').textContent.includes('Drag a step onto the canvas, or click to add it.')) throw new Error('Drag/click hint missing');
                const transfer = new DataTransfer();
                wait.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: transfer }));
                const target = document.querySelector('.wf_node.is_selected');
                target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: transfer }));
                target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
                await waitFor(() => document.querySelector('.wf_step_inspector [name="wait_hours"] input'));
                if (document.querySelector('.modal')) throw new Error('Step settings opened in a modal');
                if (document.querySelector('.wf_inspector_actions .vr')) throw new Error('Unnecessary divider on wait settings');
                const name = document.querySelector('.wf_step_inspector [name="name"] input');
                name.value = 'Dragged wait step'; name.dispatchEvent(new Event('input', { bubbles: true }));
                document.querySelector('.wf_inspector_actions .o_form_button_save').click();
                await waitFor(() => [...document.querySelectorAll('.wf_node_select')].some(node => node.textContent.includes('Dragged wait step')));
                if (workflowTitle() !== 'New employee onboarding') throw new Error('Saving a step overwrote workflow name');
                const added = [...document.querySelectorAll('.wf_node')].find(node => node.textContent.includes('Dragged wait step'));
                added.querySelector('.wf_remove_step').click();
                await waitFor(() => document.querySelector('.modal-footer .btn-primary'));
                document.querySelector('.modal-footer .btn-primary').click();
                await waitFor(() => !document.querySelector('.wf_step_inspector') && document.querySelector('.wf_builder_guide'));
                if ([...document.querySelectorAll('.wf_node_select')].some(node => node.textContent.includes('Dragged wait step'))) throw new Error('Step was not removed');
                if (document.documentElement.scrollWidth > window.innerWidth + 2) throw new Error('Horizontal page overflow');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_mobile_home_and_builder(self):
        self.browser_size = '390x844'
        self.test_home_and_builder()

    def test_overview_native_filters_and_groups(self):
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Overview search did not reach expected state');
                };
                // "Ready to use" is on by default: only templates for installed apps show.
                await waitFor(() => document.querySelector('.o_searchview_facet'));
                if (document.querySelector('.wf_template_unavailable')) throw new Error('Unavailable template shown by default');
                document.querySelector('.o_searchview_facet .o_facet_remove').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length === 11);
                await waitFor(() => document.querySelector('.wf_template_unavailable'));
                await waitFor(() => document.querySelector('.o_search_panel .o_search_panel_label[data-tooltip="CRM"]'));
                const main = document.querySelector('.o_kanban_view > main');
                if ([...main.classList].sort().join(' ') !== 'o_component_with_search_panel o_content') throw new Error('Overview main has custom layout classes');
                const panelBounds = document.querySelector('.o_search_panel').getBoundingClientRect();
                const galleryBounds = document.querySelector('.o_kanban_renderer').getBoundingClientRect();
                const cardBounds = document.querySelector('.wf_template').getBoundingClientRect();
                if (galleryBounds.left < panelBounds.right - 1 || galleryBounds.height < 100) throw new Error('Template gallery is not beside the search panel');
                if (cardBounds.top >= window.innerHeight || cardBounds.bottom <= galleryBounds.top || cardBounds.width <= 0) throw new Error('Template cards are outside the visible area');
                document.querySelector('.o_search_panel_label[data-tooltip="CRM"]').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length < 11);
                if (![...document.querySelectorAll('.wf_template')].every(card => [...card.querySelectorAll('.badge')].some(badge => badge.textContent === 'CRM'))) throw new Error('Application category does not filter cards');
                const filteredCount = document.querySelectorAll('.wf_template').length;
                document.querySelector('.o_switch_view.o_list').click();
                await waitFor(() => document.querySelectorAll('.o_list_view .o_data_row').length === filteredCount);
                if (document.querySelector('th[data-name="description"]')) throw new Error('Extra template column is not hidden by default');
                if (![...document.querySelectorAll('.o_data_row')].every(row => row.textContent.includes('CRM'))) throw new Error('Application filter was lost switching to list');
                document.querySelector('.o_switch_view.o_kanban').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length === filteredCount);
                document.querySelector('.o_search_panel_label[data-tooltip="All"]').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length === 11);
                if (document.querySelector('.o_kanban_renderer').textContent.includes('Start from a template')) throw new Error('Removed template heading remains');
                if (document.querySelectorAll('.o_kanban_renderer > article.o_card_record.o_kanban_record').length !== 11) throw new Error('Templates are not native-style article cards');
                if (!document.querySelector('.o_content > .o_kanban_renderer') || document.querySelector('.o_kanban_view .o_form_sheet, .o_kanban_view .o_form_renderer')) throw new Error('Kanban should be a direct sibling of the search panel without form wrappers');
                if (document.querySelector('.o_kanban_renderer > .wf_chips')) throw new Error('Old category buttons remain');
                const left = document.querySelector('.o_kanban_renderer');
                const toolbar = document.querySelector('.o_control_panel');
                const toolbarTop = toolbar.getBoundingClientRect().top;
                const fillers = [left].map(panel => {
                    const filler = document.createElement('div');
                    filler.style.cssText = 'height: 2000px; flex: 0 0 100%';
                    panel.appendChild(filler);
                    return filler;
                });
                left.scrollTop = 200;
                await new Promise(resolve => requestAnimationFrame(resolve));
                if (left.scrollTop !== 200) throw new Error('Template sheet does not scroll');
                if (toolbar.getBoundingClientRect().top !== toolbarTop) throw new Error('Toolbar moved while panels scrolled');
                fillers.forEach(filler => filler.remove());
                left.scrollTop = 0;
                document.querySelector('.o_searchview_dropdown_toggler').click();
                await waitFor(() => document.querySelector('.o_filter_menu'));
                const find = (selector, name) => [...document.querySelectorAll(selector)].find(n => n.textContent.trim() === name);
                for (const name of ['Reminders', 'Data updates', 'Create records', 'Scheduled', 'Integrations', 'Approvals']) {
                    if (!find('.o_filter_menu .dropdown-item', name)) throw new Error('Missing predefined filter: ' + name);
                }
                for (const name of ['Category', 'Application']) {
                    if (!find('.o_group_by_menu .dropdown-item', name)) throw new Error('Missing predefined group: ' + name);
                }
                find('.o_filter_menu .dropdown-item', 'Reminders').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length < 11);
                if (![...document.querySelectorAll('.wf_template')].every(n => n.textContent.includes('Reminders'))) throw new Error('Category filter mismatch');
                document.querySelector('.o_facet_remove').click();
                await waitFor(() => document.querySelectorAll('.wf_template').length === 11);
                if (!document.querySelector('.o_group_by_menu')) document.querySelector('.o_searchview_dropdown_toggler').click();
                await waitFor(() => find('.o_group_by_menu .dropdown-item', 'Application'));
                find('.o_group_by_menu .dropdown-item', 'Application').click();
                await waitFor(() => document.querySelectorAll('.o_kanban_header').length > 1);
                if (document.querySelectorAll('.wf_template').length !== 11) throw new Error('Grouping lost templates');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_my_workflows_navigation(self):
        self.env['workflow.definition'].with_user(self.env.ref('base.user_admin')).create({
            'name': 'Navigation test workflow',
            'model_id': self.env['ir.model']._get_id('res.partner'),
        })
        self.browser_js('/odoo/action-workflow_center.action_workflows', """
            (async () => {
                const waitFor = async (predicate) => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Workflow navigation did not reach expected state');
                };
                const menu = () => document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_my_workflows"]');
                await waitFor(() => menu() && document.querySelector('.o_kanban_renderer'));
                if (document.querySelector('.wf_home .wf_link')) throw new Error('Listing remains on overview');
                if (menu().textContent.trim() !== 'My workflows') throw new Error('Incorrect menu label');
                menu().click();
                await waitFor(() => document.querySelector('.o_list_view'));
                if (document.querySelector('.o_kanban_renderer')) throw new Error('Templates on My workflows');
                if (document.querySelector('th[data-name="description"]')) throw new Error('Optional description shown by default');
                if (!document.querySelector('.o_optional_columns')) throw new Error('Missing column selector');
                document.querySelector('.o_switch_view.o_kanban').click();
                await waitFor(() => document.querySelector('.o_kanban_record'));
                const columns = [...document.querySelectorAll('.o_kanban_header_title')];
                if (columns.length !== 3 || !['Draft', 'Active', 'Pause'].every((label, index) => columns[index].textContent.includes(label))) throw new Error('Missing or unordered workflow status columns');
                if (document.querySelector('.o_kanban_record.o_draggable')) throw new Error('Workflow cards can be dragged');
                const card = [...document.querySelectorAll('.o_kanban_record')].find(n => n.textContent.includes('Navigation test workflow'));
                if (!card) throw new Error('Workflow missing in kanban');
                card.click();
                await waitFor(() => document.querySelector('.wf_builder'));
                menu().click();
                await waitFor(() => document.querySelector('.o_switch_view.o_list'));
                document.querySelector('.o_switch_view.o_list').click();
                await waitFor(() => document.querySelector('.o_list_view'));
                const flow = [...document.querySelectorAll('.o_data_row')].find(n => n.textContent.includes('Navigation test workflow'));
                if (!flow) throw new Error('Existing workflow missing');
                flow.click();
                await waitFor(() => document.querySelector('.wf_builder'));
                if (!document.querySelector('.o_control_panel').textContent.includes('Navigation test workflow')) throw new Error('Wrong builder opened');
                menu().click();
                await waitFor(() => document.querySelector('.o_list_view'));
                document.querySelector('.o_list_button_add').click();
                await waitFor(() => document.querySelector('.o_form_sheet .wf_start_blank'));
                const select = document.querySelector('#wf_document');
                const contact = [...select.options].find(option => option.textContent === 'Contact');
                if (!contact) throw new Error('Missing Contact document');
                select.value = contact.value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                const description = document.querySelector('#wf_description');
                description.value = 'Review new customer registrations.';
                description.dispatchEvent(new Event('input', { bubbles: true }));
                const form = document.querySelector('.o_form_view');
                const url = window.location.href;
                document.querySelector('.wf_start_blank').click();
                await waitFor(() => document.querySelector('.o_form_view [name="model_id"] input')?.value === 'Contact');
                if (document.querySelector('.o_form_view') !== form || window.location.href !== url) throw new Error('Start blank navigated away from the current form');
                if (document.querySelector('.modal')) throw new Error('Start blank opened a modal');
                if (document.querySelector('[name="model_id"] input').value !== 'Contact') throw new Error('Document not prefilled');
                if (document.querySelector('[name="description"] textarea').value !== 'Review new customer registrations.') throw new Error('Description not prefilled');
                document.querySelector('.o_control_panel_main_buttons .o_workflow_open_builder').click();
                await waitFor(() => document.querySelector('.wf_builder'));
                if (!document.querySelector('.wf_trigger').textContent.includes('Contact')) throw new Error('Toolbar action did not save and open the selected workflow');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_run_history_search_views_and_pagination(self):
        from odoo.addons.workflow_center.models.workflow import internal
        env = self.env(user=self.env.ref('base.user_admin'))
        partner = env['res.partner'].create({'name': 'History paging customer'})
        flow = env['workflow.definition'].create({
            'name': 'History paging workflow', 'model_id': env['ir.model']._get('res.partner').id,
        })
        internal(env['workflow.run']).create([{
            'workflow_id': flow.id, 'record_id': partner.id, 'revision': flow.revision,
            'name': 'History paging %02d' % index, 'is_test': True, 'state': 'done',
        } for index in range(81)])
        self.browser_js('/odoo/action-workflow_center.action_run_history', """
            (async () => {
                const waitFor = async predicate => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Run history controls did not reach expected state');
                };
                await waitFor(() => document.querySelectorAll('.o_data_row').length === 80);
                document.querySelector('.o_control_panel .o_pager_next').click();
                await waitFor(() => document.querySelectorAll('.o_data_row').length === 1);
                document.querySelector('.o_control_panel .o_pager_previous').click();
                await waitFor(() => document.querySelectorAll('.o_data_row').length === 80);
                document.querySelector('.o_switch_view.o_kanban').click();
                await waitFor(() => document.querySelector('.o_kanban_record:not(.o_kanban_ghost)'));
                const checkColumns = () => {
                    const columns = [...document.querySelectorAll('.o_kanban_header_title')];
                    if (columns.length !== 5 || !['Running', 'Waiting', 'Failed', 'Done', 'Stopped'].every((label, index) => columns[index].textContent.includes(label))) throw new Error('Missing or unordered run status columns');
                };
                checkColumns();
                document.querySelector('.o_searchview_dropdown_toggler').click();
                await waitFor(() => document.querySelector('.o_filter_menu'));
                const item = (selector, label) => [...document.querySelectorAll(selector)].find(el => el.textContent.trim() === label);
                for (const label of ['Running', 'Waiting', 'Failed', 'Done', 'Stopped', 'Previews', 'Live runs', 'Uncertain delivery']) {
                    if (!item('.o_filter_menu .dropdown-item', label)) throw new Error('Missing filter ' + label);
                }
                item('.o_filter_menu .dropdown-item', 'Failed').click();
                await waitFor(() => !document.querySelector('.o_kanban_record:not(.o_kanban_ghost)') && document.querySelector('.o_searchview_facet'));
                checkColumns();
                document.querySelector('.o_facet_remove').click();
                await waitFor(() => document.querySelector('.o_kanban_record:not(.o_kanban_ghost)'));
                if (!document.querySelector('.o_group_by_menu')) document.querySelector('.o_searchview_dropdown_toggler').click();
                await waitFor(() => item('.o_group_by_menu .dropdown-item', 'Status'));
                item('.o_group_by_menu .dropdown-item', 'Status').click();
                await waitFor(() => document.querySelector('.o_kanban_group'));
                document.querySelector('.o_switch_view.o_list').click();
                await waitFor(() => document.querySelector('.o_group_header'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

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
                const failedRow = () => [...document.querySelectorAll('.o_data_row')].find(row => row.textContent.includes('UI customer follow-up') && row.textContent.includes('Failed'));
                await waitFor(failedRow);
                failedRow().querySelector('.o_data_cell').click();
                await waitFor(() => document.querySelector('.o_form_view button[name="action_retry"]'));
                if (!document.querySelector('.o_form_view').innerText.includes('Temporary test failure')) throw new Error('Failure not explained');
                document.querySelector('.o_form_view button[name="action_retry"]').click();
                await waitFor(() => document.querySelector('.modal-footer .btn-primary'));
                document.querySelector('.modal-footer .btn-primary').click();
                await waitFor(() => document.querySelector('.o_arrow_button_current[data-value="done"]'));
                document.querySelector('.o_form_view button[name="action_open_workflow"]').click();
                await waitFor(() => document.querySelector('.wf_builder'));
                document.querySelector('.o_control_panel .wf_preview').click();
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
        self.browser_js('/odoo/action-workflow_center.action_my_workflows', """
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
                await waitFor(() => [...document.querySelectorAll('.o_data_row')].some(n => n.textContent.includes('Branch and create UI')));
                [...document.querySelectorAll('.o_data_row')].find(n => n.textContent.includes('Branch and create UI')).click();
                await waitFor(() => document.querySelectorAll('.wf_branch_paths > section').length === 2);
                const paths = document.querySelectorAll('.wf_branch_paths > section');
                if (!paths[0].innerText.includes('Create follow-up contact') || !paths[1].innerText.includes('Wait for contact details')) throw new Error('Branch paths are mixed');
                paths[0].querySelector('.wf_node_select').click();
                await waitFor(() => document.querySelector('.wf_step_inspector [name="create_model_id"] input'));
                await choose(document.querySelector('.wf_step_inspector [name="create_model_id"] input'), 'Contact');
                await waitFor(() => document.querySelector('.wf_step_inspector [name="value_ids"] .o_field_x2many_list_row_add button'));
                document.querySelector('.wf_step_inspector [name="value_ids"] .o_field_x2many_list_row_add button').click();
                await waitFor(() => document.querySelector('.modal [name="field_id"] input'));
                await choose(document.querySelector('.modal [name="field_id"] input'), 'Name');
                await waitFor(() => document.querySelector('.modal [name="text_value"] input'));
                const text = document.querySelector('.modal [name="text_value"] input');
                text.value = 'UI created record'; text.dispatchEvent(new Event('input', {bubbles: true}));
                [...document.querySelectorAll('.modal-footer button')].find(n => n.textContent.trim() === 'Save & Close').click();
                await waitFor(() => !document.querySelector('.modal'));
                document.querySelector('.wf_inspector_actions .o_form_button_save').click();
                await waitFor(() => document.querySelector('.wf_inspector_actions .o_form_button_save:not([disabled])'));
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
                await waitFor(() => document.querySelector('.wf_template'));
                for (const suffix of ['my_workflows', 'workflows_runs']) {
                    await waitFor(() => document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_' + suffix + '"]'));
                }
                if (document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_approvals"]')) throw new Error('Unexpected approval shortcut');
                document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows_runs"]').click();
                await waitFor(() => document.querySelector('.o_list_renderer'));
                document.querySelector('.o_switch_view.o_kanban').click();
                await waitFor(() => document.querySelector('.o_kanban_renderer'));
                document.querySelector('.o_main_navbar [data-menu-xmlid="workflow_center.menu_workflows"]').click();
                await waitFor(() => document.querySelector('.wf_template'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
