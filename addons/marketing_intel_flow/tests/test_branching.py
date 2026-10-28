import json
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal


@tagged('post_install', '-at_install')
class TestBranchingFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, default_phase='planning', default_proposal_state='approved'))
        if 'crm.lead' not in cls.env:
            cls.skipTest(cls, 'CRM is needed for form leads')
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        cls.marketer = new_test_user(cls.env, 'mib_marketer', groups='marketing_intel.group_mi_user,ai_agent.group_user')
        cls.approver = new_test_user(cls.env, 'mib_approver', groups='marketing_intel.group_mi_user,'
                                                                     'approval_center.group_approval_center_approver')
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Flow engine', 'url': 'https://hermes.example.com', 'secret_reference': 'AI_AGENT_SECRET_TEST',
            'management_url': 'https://hermes.example.com', 'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Sorter', 'engine_id': engine.id,
                                               'user_ids': [Command.set([cls.marketer.id])]})
        cls.agent.action_activate()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io', 'ai_agent_id': cls.agent.id,
                                                       'email_from': 'hello@metric.io'})
        policy = cls.env.ref('marketing_intel_flow.policy_flow').sudo()
        policy.company_id = cls.env.company
        policy.approver_ids = [Command.clear(), Command.create({'user_id': cls.approver.id, 'required': True})]
        cls.website = cls.env.ref('utm.utm_medium_website')

    def _flow(self, split):
        flow = self.env['mi.flow'].with_user(self.marketer).create({
            'name': 'Form split', 'brand_id': self.brand.id, 'trigger': 'form_submit', 'form_kind': 'lead',
            'step_ids': [Command.create(dict({'sequence': 1, 'action': 'split'}, **split)),
                         Command.create({'sequence': 2, 'action': 'email', 'path': 'a', 'subject': 'Demo, {first_name}?',
                                         'message': 'Hi {first_name}, pick a time.'}),
                         Command.create({'sequence': 3, 'action': 'sms', 'path': 'b',
                                         'message': 'Hi {first_name}, thanks!'})]})
        flow.action_request_approval()
        flow.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(flow.state, 'active')
        return flow

    def _lead(self, name, text, email, phone, probability=10):
        return self.env['crm.lead'].sudo().create({
            'name': name, 'description': text, 'email_from': email, 'phone': phone, 'contact_name': name,
            'medium_id': self.website.id, 'probability': probability, 'company_id': self.env.company.id})

    def test_paths_are_checked_before_approval(self):
        flow = self.env['mi.flow'].with_user(self.marketer).create({
            'name': 'Bad', 'brand_id': self.brand.id, 'trigger': 'form_submit',
            'step_ids': [Command.create({'sequence': 1, 'action': 'email', 'path': 'a', 'subject': 'x', 'message': 'y'})]})
        with self.assertRaisesRegex(UserError, 'need a “Split the audience” step'):
            flow.action_request_approval()
        flow.step_ids = [Command.create({'sequence': 0, 'action': 'split', 'split_by': 'words'})]
        with self.assertRaisesRegex(UserError, 'words that send people'):
            flow.action_request_approval()

    def test_words_split_sends_email_or_sms(self):
        flow = self._flow({'split_by': 'words', 'split_words': 'demo, price'})
        hot = self._lead('Aisha Rahman', '<p>Can I get a demo next week?</p>', 'aisha@example.com', '+60123456789')
        cold = self._lead('Ben Lim', '<p>Just browsing</p>', 'ben@example.com', '+60198765432')
        self.env['mail.blacklist'].sudo()._add('gone@example.com')
        gone = self._lead('Gone Person', '<p>demo please</p>', 'gone@example.com', '+60111111111')
        flow._run_once()
        runs = {r.person: r for r in flow.run_ids}
        self.assertEqual(runs['Aisha Rahman'].path, 'a')
        self.assertEqual(runs['Ben Lim'].path, 'b')
        mail = self.env['mail.mail'].sudo().search([('email_to', '=', 'aisha@example.com')])
        self.assertEqual(mail.subject, 'Demo, Aisha?')
        self.assertIn('pick a time', mail.body_html)
        sms = self.env['sms.sms'].sudo().search([('body', '=', 'Hi Ben, thanks!')])
        self.assertTrue(sms)
        self.assertFalse(self.env['mail.mail'].sudo().search([('email_to', '=', 'ben@example.com')]))
        self.assertEqual(runs['Gone Person'].state, 'skipped')
        self.assertIn('unsubscribed', runs['Gone Person'].log)
        self.assertEqual(runs['Aisha Rahman'].message_count, 1)
        # leads that did not come from a website form are ignored
        self.env['crm.lead'].sudo().create({'name': 'Phone call', 'email_from': 'x@example.com'})
        flow._run_once()
        self.assertEqual(len(flow.run_ids), 3)
        self.assertTrue(hot and cold and gone)

    def test_ai_split_waits_for_the_answer_then_continues(self):
        flow = self._flow({'split_by': 'ai', 'split_question': 'asks for a price or a demo'})
        self._lead('Chen Wei', '<p>What does it cost for 5 users?</p>', 'chen@example.com', '+60122222222')
        flow._run_once()
        run = flow.run_ids
        self.assertEqual(run.state, 'waiting')
        self.assertTrue(run.ai_run_id)
        self.assertIn('What does it cost', run.ai_run_id.sudo().prompt)
        self.assertFalse(self.env['mail.mail'].sudo().search([('email_to', '=', 'chen@example.com')]))
        ai_run = run.ai_run_id.sudo()
        agent_internal(ai_run).write({'state': 'completed', 'answer': json.dumps(
            {'path': 'a', 'reason': 'Asks for the price.'})})
        ai_run._notify_origin()
        self.assertEqual((run.state, run.path), ('done', 'a'))
        self.assertIn('Asks for the price', run.log)
        self.assertTrue(self.env['mail.mail'].sudo().search([('email_to', '=', 'chen@example.com')]))
        self.assertFalse(self.env['sms.sms'].sudo().search([('number', 'like', '122222222')]))

    def test_unusable_ai_answer_goes_to_path_b(self):
        flow = self._flow({'split_by': 'ai', 'split_question': 'ready to buy'})
        self._lead('Dina', '<p>hello</p>', 'dina@example.com', '+60133333333')
        flow._run_once()
        ai_run = flow.run_ids.ai_run_id.sudo()
        agent_internal(ai_run).write({'state': 'completed', 'answer': 'I think maybe?'})
        ai_run._notify_origin()
        self.assertEqual(flow.run_ids.path, 'b')
        self.assertTrue(self.env['sms.sms'].sudo().search([('body', '=', 'Hi Dina, thanks!')]))

    def test_recipe_builds_the_branching_flow(self):
        recipe = self.env.ref('marketing_intel_flow.recipe_form_split')
        flow = self.env['mi.flow'].browse(recipe.with_user(self.marketer).with_context(
            default_brand_id=self.brand.id).action_use()['res_id'])
        self.assertEqual((flow.trigger, flow.path_a_name, flow.path_b_name), ('form_submit', 'High intent', 'Low intent'))
        self.assertEqual(flow.step_ids.mapped('action'), ['split', 'email', 'sms'])
        self.assertEqual(flow.step_ids.mapped('path'), ['all', 'a', 'b'])
        self.assertIn('High intent', flow._approval_text())
