from unittest.mock import patch

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal


@tagged('post_install', '-at_install')
class TestAssistantChatUI(HttpCase):
    """Approved mocks 2026-11-08, boards 10 and 12: assistants in Discuss."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        engine = cls.env['ai.agent.engine'].create({'name': 'UI engine', 'url': 'https://hermes.example.com',
            'secret_reference': 'AI_AGENT_SECRET_TEST', 'management_url': 'https://hermes.example.com',
            'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        internal(engine).write({'state': 'ready'})
        cls.person = new_test_user(cls.env, 'discuss_ui_person', password='discuss_ui_person',
                                   groups='base.group_user,ai_agent.group_user')
        hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        Agent = cls.env['ai.agent']
        helper = Agent.create({'name': 'HR policy helper', 'description': 'Leave and onboarding',
                               'engine_id': engine.id, 'department_id': hr.id,
                               'user_ids': [Command.set(cls.person.ids)]})
        paused = Agent.create({'name': 'Finance helper', 'engine_id': engine.id,
                               'user_ids': [Command.set(cls.person.ids)]})
        (helper | paused).action_activate()
        paused.action_pause()

    def test_assistants_filter_label_and_chat_intro(self):
        self.browser_js('/odoo/discuss', """
            (async () => {
                const wait = async (p, what) => {
                    for (let i = 0; i < 150; i++) { if (p()) return; await new Promise(r => setTimeout(r, 100)); }
                    throw new Error(what + ' missing: ' + document.body.innerText.slice(0, 1500));
                };
                const chip = () => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Assistants');
                await wait(chip, 'Assistants filter');
                chip().click();
                const items = () => [...document.querySelectorAll('.o-mail-MessagingMenuItem')];
                await wait(() => items().some(i => i.textContent.includes('HR policy helper')), 'Assistant chat');
                const helper = items().find(i => i.textContent.includes('HR policy helper'));
                if (!helper.querySelector('.o_ai_discuss_label')) throw new Error('AI label missing');
                if (!helper.textContent.includes('Human Resources · Leave and onboarding')) throw new Error('Preview missing: ' + helper.textContent);
                const paused = items().find(i => i.textContent.includes('Finance helper'));
                if (!paused || !paused.classList.contains('o_ai_discuss_paused')) throw new Error('Paused assistant not greyed out');
                if (!paused.textContent.includes('Paused')) throw new Error('Paused text missing');
                (helper.querySelector('.o-mail-NotificationItem') || helper).click();
                await wait(() => document.body.innerText.includes('the Human Resources assistant. It answers with what you may see'), 'Chat intro');
                // An assistant is not a person: no calls, no profile card.
                const titles = [...document.querySelectorAll('button[title], button[aria-label]')]
                    .map(b => b.getAttribute('title') || b.getAttribute('aria-label'));
                if (titles.some(t => /Start (Video )?Call/.test(t))) throw new Error('Calls offered: ' + titles.join(', '));
                const avatar = document.querySelector('.o-mail-Thread-avatar');
                if (avatar) {
                    avatar.click();
                    await new Promise(r => setTimeout(r, 500));
                    if (document.querySelector('.o_avatar_card')) throw new Error('Profile card opened');
                }
                console.log('test successful');
            })();
        """, login='discuss_ui_person', timeout=120)
