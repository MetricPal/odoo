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
