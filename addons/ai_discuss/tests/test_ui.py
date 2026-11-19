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


@tagged('post_install', '-at_install')
class TestChatterAssistantsUI(HttpCase):
    """Approved board 11 (2026-11-08): the chatter's Assistants button and its box (ADR 0013 phase 3)."""

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
        cls.person = new_test_user(cls.env, 'chatter_ui_person', password='chatter_ui_person',
                                   groups='base.group_user,ai_agent.group_user,base.group_partner_manager')
        hr = cls.env['hr.department'].create({'name': 'Human Resources'})
        Agent = cls.env['ai.agent']
        for name, description in (('Customer helper', 'Customers and their history'),
                                  ('Second helper', 'Another one')):
            Agent.create({'name': name, 'description': description, 'engine_id': engine.id,
                          'department_id': hr.id, 'user_ids': [Command.set(cls.person.ids)],
                          'access_ids': [Command.create({'model_name': 'res.partner', 'field_names': 'name'})]
                          }).action_activate()
        cls.customer = cls.env['res.partner'].create({'name': 'Hannah Glover'})

    def test_ask_an_assistant_from_the_chatter(self):
        with patch.object(type(self.env['ai.agent']), '_context_for', return_value={}):
            self.browser_js(f'/odoo/res.partner/{self.customer.id}', """
                (async () => {
                    const wait = async (p, what) => {
                        for (let i = 0; i < 150; i++) { if (p()) return; await new Promise(r => setTimeout(r, 100)); }
                        throw new Error(what + ' missing: ' + document.body.innerText.slice(0, 1500));
                    };
                    const button = () => document.querySelector('.o_ai_chatter_assistants');
                    await wait(button, 'Assistants button');
                    const order = [...button().parentElement.querySelectorAll('button')].map(b => b.textContent.trim());
                    if (order.indexOf('Assistants') !== order.indexOf('Log note') + 1) throw new Error('Order: ' + order);
                    button().click();
                    const box = () => document.querySelector('#o_ai_chatter_ask_box');
                    await wait(box, 'Ask box');
                    if (document.querySelector('.o-mail-Composer')) throw new Error('Message composer also open');
                    if (box().placeholder !== 'Ask Customer helper about this contact…') throw new Error('Placeholder: ' + box().placeholder);
                    if (!document.body.innerText.includes('Answers in an internal note · uses your access rights')) throw new Error('Hint missing');
                    document.querySelector('.o_ai_chatter_ask_to').click();
                    await wait(() => document.body.innerText.includes('Another one'), 'Assistant picker');
                    [...document.querySelectorAll('.o_ai_chatter_ask_option')].find(o => o.textContent.includes('Second helper')).click();
                    await wait(() => box().placeholder === 'Ask Second helper about this contact…', 'Chosen assistant');
                    box().value = 'How long has she been a customer?';
                    box().dispatchEvent(new Event('input', { bubbles: true }));
                    await wait(() => ![...document.querySelectorAll('.o_ai_chatter_ask button')].find(b => b.textContent.trim() === 'Send').disabled, 'Send enabled');
                    [...document.querySelectorAll('.o_ai_chatter_ask button')].find(b => b.textContent.trim() === 'Send').click();
                    await wait(() => !box(), 'Box closed after sending');
                    await wait(() => document.body.innerText.includes('Asked Second helper'), 'Question note');
                    console.log('test successful');
                })();
            """, login='chatter_ui_person', timeout=120)
        asked = self.env['ai.chatter.question'].sudo().search([('res_id', '=', self.customer.id)])
        self.assertEqual((asked.agent_id.name, asked.question), ('Second helper', 'How long has she been a customer?'))
