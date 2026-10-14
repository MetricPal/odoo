from unittest.mock import patch

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.tests.common import ChromeBrowser

from ..models.common import internal


@tagged('post_install', '-at_install')
class TestAgentUI(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.staff = mail_new_test_user(cls.env, login='ai_ui_staff', groups='ai_agent.group_user',
                                      notification_type='inbox')
        with patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443'}):
            cls.engine = cls.env['ai.agent.engine'].create({'name': 'UI engine', 'url': 'https://hermes.example.com',
                'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
                'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(cls.engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'UI Sales Assistant', 'engine_id': cls.engine.id,
            'description': 'Prepare supervised sales work', 'user_ids': [Command.set((cls.staff | cls.env.user).ids)]})
        cls.agent.action_activate()

    def _capture(self):
        original = ChromeBrowser._handle_console
        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value', '').startswith('ai_agent_capture_'):
                browser.take_screenshot(prefix=args[0]['value'] + '_')
            return original(browser, type, args=args, **kwargs)
        self.patch(ChromeBrowser, '_handle_console', capture)

    def test_manager_native_agent_form(self):
        self._capture()
        self.browser_js('/odoo/action-ai_agent.action_agents', """
            (async () => {
                const wait = async predicate => {
                    for (let i=0;i<150;i++) { if (predicate()) return; await new Promise(r=>setTimeout(r,100)); }
                    throw new Error('AI page missing: ' + document.body.innerText.slice(-1200));
                };
                await wait(()=>document.querySelector('.o_kanban_record'));
                console.log('ai_agent_capture_agents');
                const configure = [...document.querySelectorAll('.o_kanban_record button')].find(b=>b.textContent.trim()==='Configure');
                if (!configure) throw new Error('Manager configuration action missing');
                configure.click();
                await wait(()=>document.querySelector('.o_form_sheet [name="system_prompt"]'));
                if (!document.querySelector('.o_form_sheet [name="name"]')) throw new Error('Name outside native sheet');
                if (!document.querySelector('.o-mail-ChatterContainer')) throw new Error('Native chatter missing');
                const tabs = [...document.querySelectorAll('.o_notebook .nav-link')];
                const dataTab = tabs.find(t=>t.textContent.includes('Data access'));
                if (!dataTab) throw new Error('Data access tab missing');
                dataTab.click();
                await wait(()=>document.body.innerText.includes('Business changes and external actions are disabled'));
                console.log('ai_agent_capture_access');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_agent_audience_form(self):
        self.agent.action_pause()
        department = self.env['hr.department'].create({'name': 'Sales', 'company_id': self.env.company.id})
        self.agent.write({'access_scope': 'departments', 'department_ids': [Command.set(department.ids)]})
        self._capture()
        self.browser_js(f'/odoo/action-ai_agent.action_agents/{self.agent.id}', """
            (async () => {
                for (let i=0;i<150;i++) {
                    if (document.querySelector('[name="access_scope"]')) break;
                    await new Promise(r=>setTimeout(r,100));
                }
                const scope = document.querySelector('[name="access_scope"]');
                if (!scope) throw new Error('Audience selector missing');
                scope.querySelector('.o_select_menu_toggler').click();
                await new Promise(r=>setTimeout(r,300));
                for (const label of ['Company', 'Departments', 'Selected users']) {
                    if (!document.body.innerText.includes(label)) throw new Error('Missing scope '+label);
                }
                if (!document.querySelector('[name="department_ids"]')) throw new Error('Department selector missing');
                if (document.querySelector('[name="user_ids"]')) throw new Error('Individual users shown for department scope');
                if (document.querySelectorAll('[name="response_style"] input[type="radio"]').length !== 4) throw new Error('Response styles must be radio choices');
                if (!document.body.innerText.includes('Concise, engaging, and dynamic.')) throw new Error('Style description missing');
                console.log('ai_agent_capture_department_scope');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_staff_chat_has_no_configuration(self):
        self._capture()
        self.browser_js('/odoo/action-ai_agent.action_agents', """
            (async () => {
                const wait = async predicate => {
                    for (let i=0;i<150;i++) { if (predicate()) return; await new Promise(r=>setTimeout(r,100)); }
                    throw new Error('Staff page missing: ' + document.body.innerText.slice(-1200));
                };
                await wait(()=>document.querySelector('.o_kanban_record'));
                const buttons=[...document.querySelectorAll('.o_kanban_record button')];
                if (buttons.some(b=>b.textContent.trim()==='Configure')) throw new Error('Staff configuration action exposed');
                const chat=buttons.find(b=>b.textContent.trim()==='Chat');
                if (!chat) throw new Error('Staff chat action missing');
                chat.click();
                await wait(()=>document.querySelector('.modal [name="prompt"] textarea'));
                if (!document.querySelector('.modal').textContent.includes('cannot change records')) throw new Error('Request scope missing');
                console.log('ai_agent_capture_chat');
                console.log('test successful');
            })();
        """, login='ai_ui_staff', timeout=90)

    def test_connection_form_masks_keys_and_hides_references(self):
        self._capture()
        self.browser_js('/odoo/action-ai_agent.action_engines', """
            (async () => {
                const wait = async p => { for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Connection form missing: '+document.body.innerText.slice(-1000));};
                await wait(()=>document.querySelector('.o_list_button_add'));
                document.querySelector('.o_list_button_add').click();
                await wait(()=>document.querySelector('.o_form_sheet [name="connection_mode"]'));
                const label=[...document.querySelectorAll('.o_form_sheet label')].find(l=>l.textContent.trim()==='Connection name');
                if(!label)throw new Error('Connection name label missing');
                const name=document.querySelector('.o_form_sheet [name="name"] input');
                if(!name?.placeholder || name.value!=='Local Hermes')throw new Error('Local name/default placeholder missing');
                if(document.querySelector('[name="secret_reference"], [name="management_secret_reference"]'))throw new Error('Internal credential reference exposed');
                console.log('ai_agent_capture_local_connection');
                document.querySelector('[name="connection_mode"] input[data-value="remote"]').click();
                await wait(()=>document.querySelector('[name="api_key"] input'));
                const key=document.querySelector('[name="api_key"] input');
                if(key.type!=='password')throw new Error('API key not masked');
                if(!document.querySelector('[name="url"] input')?.placeholder?.startsWith('https://'))throw new Error('URL placeholder missing');
                await wait(()=>document.querySelector('[name="management_same_connection"] input'));
                const same=document.querySelector('[name="management_same_connection"] input');
                if(!same.checked)throw new Error('Same management connection must default on for new remote connection');
                if(document.querySelector('[name="management_api_key"] input'))throw new Error('Separate key shown while sharing connection');
                same.click();
                await wait(()=>document.querySelector('[name="management_api_key"] input'));
                if(document.querySelector('[name="management_api_key"] input').type!=='password')throw new Error('Management key not masked');
                console.log('ai_agent_capture_remote_connection');
                document.querySelector('.o_form_button_cancel').click();
                await wait(()=>!!document.querySelector('.o_list_button_add'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_source_and_skill_forms_have_clear_names_and_content(self):
        source = self.env['ai.agent.source'].create({'name': 'UI Product Guide', 'text': 'Prepared reference content for browser verification.'})
        skill = self.env['ai.agent.skill'].create({'name': 'UI Summarize', 'instructions': 'Summarize permitted records.'})
        self._capture()
        self.browser_js(f'/odoo/action-ai_agent.action_sources/{source.id}', """
            (async () => {
                const wait = async p => {for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Source form missing: '+document.body.innerText.slice(-1000));};
                await wait(()=>document.querySelector('.o_form_sheet [name="name"]'));
                if(![...document.querySelectorAll('label')].some(l=>l.textContent.trim()==='Source name'))throw new Error('Source name label missing');
                if(document.querySelector('[name="user_ids"]'))throw new Error('Per-person reader selector exposed');
                if(document.querySelector('.o_form_sheet .alert-success'))throw new Error('Source success banner still present');
                if(!document.body.innerText.includes('Extracted content'))throw new Error('Prepared preview tab not named clearly');
                console.log('ai_agent_capture_source');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
        self.browser_js(f'/odoo/action-ai_agent.action_skills/{skill.id}', """
            (async () => {
                const wait=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Skill form missing');};
                await wait(()=>document.querySelector('.o_form_sheet [name="instructions"]'));
                if(![...document.querySelectorAll('label')].some(l=>l.textContent.trim()==='Skill name'))throw new Error('Skill name label missing');
                if(!document.body.innerText.includes('Instructions'))throw new Error('Instructions heading missing');
                console.log('ai_agent_capture_skill');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_conversation_and_request_forms_show_full_answer(self):
        conversation = internal(self.env['ai.agent.conversation']).create({'name': 'UI conversation', 'agent_id': self.agent.id, 'user_id': self.env.user.id})
        run = internal(self.env['ai.agent.run']).create({'name': 'UI request', 'conversation_id': conversation.id, 'prompt': 'Explain permitted context', 'answer': 'A full answer for form verification.', 'state': 'completed'})
        self._capture()
        self.browser_js(f'/odoo/action-ai_agent.action_conversations/{conversation.id}', """
            (async()=>{
                const wait=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Conversation form missing');};
                await wait(()=>document.body.innerText.includes('A full answer for form verification.'));
                if(!document.body.textContent.includes('Questions & answers'))throw new Error('Readable conversation heading missing');
                console.log('ai_agent_capture_conversation');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
        self.browser_js(f'/odoo/action-ai_agent.action_activity/{run.id}', """
            (async()=>{
                const wait=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Request form missing');};
                await wait(()=>document.body.innerText.includes('A full answer for form verification.'));
                if(!document.body.textContent.includes('Your question'))throw new Error('Request question heading missing');
                console.log('ai_agent_capture_request');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)


    def test_persistent_catalog_enables_multiple_models(self):
        catalog = {'provider': 'nous', 'model': 'example/current', 'providers': [
            {'slug': 'nous', 'name': 'Nous Portal', 'authenticated': True, 'models': ['example/current', 'example/other']},
            {'slug': 'anthropic', 'name': 'Anthropic', 'authenticated': False, 'models': []}]}
        internal(self.engine).write({'models_catalog': catalog})
        self._capture()
        with patch.object(type(self.engine), '_request', return_value=catalog):
            self.browser_js(f'/odoo/action-ai_agent.action_engines/{self.engine.id}', """
                (async()=>{
                    const wait=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Catalog flow missing: '+document.body.innerText);};
                    await wait(()=>document.querySelector('.o_notebook'));
                    if(document.querySelector('.o_form_statusbar .o_ai_connection_status, .o_form_statusbar .o_statusbar_status'))throw new Error('Connection status decoration still present');
                    if(document.querySelector('.o_form_sheet .alert-info'))throw new Error('Success banner still present');
                    console.log('ai_agent_capture_engine_status');
                    if(!document.querySelector('button[name="action_models"]'))throw new Error('Add model missing');
                    if(!document.querySelector('[name="management_same_connection"]'))throw new Error('Management not in main setup');
                    [...document.querySelectorAll('.o_notebook .nav-link')].find(t=>t.textContent.includes('Providers & models')).click();
                    document.querySelector('button[name="action_models"]').click();
                    await wait(()=>document.querySelectorAll('.modal .o_ai_picker_models input[type="checkbox"]').length===2);
                    const first=()=>document.querySelectorAll('.o_ai_picker_models input[type="checkbox"]')[0];
                    first().click();
                    await wait(()=>document.querySelectorAll('.modal .o_ai_picker_models .badge').length===1 &amp;&amp; !first().disabled);
                    document.querySelectorAll('.o_ai_picker_models input[type="checkbox"]')[1].click();
                    await wait(()=>document.querySelectorAll('.modal .o_ai_picker_models .badge').length===2 &amp;&amp; !first().disabled);

                    document.querySelector('.o_ai_model_picker').scrollIntoView({block:'start'});
                    console.log('ai_agent_capture_persistent_models');
                    [...document.querySelectorAll('.o_ai_picker_providers button')].find(b=>b.textContent.includes('Anthropic')).click();
                    await wait(()=>document.body.innerText.includes('Authenticate this provider'));
                    [...document.querySelectorAll('.modal footer button')].find(b=>b.textContent.trim()==='Close').click();
                    await wait(()=>!document.querySelector('.modal .o_ai_model_picker'));
                    await wait(()=>document.querySelectorAll('[name="enabled_model_ids"] .o_data_row').length===2);
                    if(![...document.querySelectorAll('a')].some(a=>a.textContent.trim()==='Model Settings'))throw new Error('Settings hyperlink missing');
                    console.log('test successful');
                })();
            """.replace('&amp;', '&'), login='admin', timeout=90)
        self.engine.invalidate_recordset(['enabled_model_ids'])
        self.assertEqual(len(self.engine.enabled_model_ids), 2)

    def test_agent_selects_from_enabled_models(self):
        self.agent.action_pause()
        catalog = {'provider': 'nous', 'model': 'example/current', 'providers': [
            {'slug': 'nous', 'name': 'Nous Portal', 'authenticated': True, 'models': ['example/current', 'example/other']}]}
        with patch.object(type(self.engine), '_request', return_value=catalog):
            self.engine.set_model_enabled('nous', 'example/other', True)
        self.browser_js(f'/odoo/action-ai_agent.action_agents/{self.agent.id}', """
            (async()=>{
                const wait=async p=>{for(let i=0;i<150;i++){if(p())return;await new Promise(r=>setTimeout(r,100));}throw new Error('Agent model selection missing');};
                await wait(()=>document.querySelector('.o_notebook'));
                [...document.querySelectorAll('.o_notebook .nav-link')].find(t=>t.textContent.includes('Engine & limits')).click();
                await wait(()=>document.querySelector('[name="engine_model_id"] input'));
                const input=document.querySelector('[name="engine_model_id"] input');
                input.click();input.value='example/other';input.dispatchEvent(new Event('input',{bubbles:true}));
                await wait(()=>[...document.querySelectorAll('.o-autocomplete--dropdown-item')].some(e=>e.textContent.includes('example/other')));
                [...document.querySelectorAll('.o-autocomplete--dropdown-item')].find(e=>e.textContent.includes('example/other')).click();
                await wait(()=>document.querySelector('.o_form_dirty'));
                document.querySelector('.o_form_button_save').click();
                await wait(()=>!document.querySelector('.o_form_dirty'));
                document.querySelector('[data-menu-xmlid="ai_agent.menu_agents"]').click();
                await wait(()=>document.querySelector('.o_kanban_record'));
                console.log('test successful');
            })();
        """, login='admin', timeout=90)
        self.agent.invalidate_recordset(['engine_model_id', 'model'])
        self.assertEqual(self.agent.model, 'example/other')
