from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ai_agent.models.common import internal as agent_internal


@tagged('post_install', '-at_install')
class TestWritingTools(TransactionCase):
    """Writing tools on marketing texts (plan M2, approved boards 8.1 to 8.4, 2026-11-11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env_patch = patch.dict('os.environ', {'AI_AGENT_ENDPOINTS': 'hermes.example.com:443',
                                              'AI_AGENT_SECRET_TEST': 'synthetic-not-a-live-key'})
        env_patch.start()
        cls.addClassCleanup(env_patch.stop)
        groups = ('marketing_intel.group_mi_user,ai_agent.group_user,mass_mailing.group_mass_mailing_user,'
                  'messaging_marketing.group_mm_user')
        cls.user = new_test_user(cls.env, 'miw_user', groups=groups)
        cls.other = new_test_user(cls.env, 'miw_other', groups=groups)
        cls.outsider = new_test_user(cls.env, 'miw_outsider', groups='marketing_intel.group_mi_user,ai_agent.group_user')
        manager = new_test_user(cls.env, 'miw_manager', groups='marketing_intel.group_mi_manager')
        engine = cls.env['ai.agent.engine'].create({
            'name': 'Writing engine', 'url': 'https://hermes.example.com', 'secret_reference': 'AI_AGENT_SECRET_TEST',
            'management_url': 'https://hermes.example.com', 'management_secret_reference': 'AI_AGENT_SECRET_TEST'})
        agent_internal(engine).write({'state': 'ready'})
        cls.agent = cls.env['ai.agent'].create({'name': 'Marketing Assistant', 'engine_id': engine.id,
                                               'user_ids': [Command.set([cls.user.id, cls.other.id, cls.outsider.id])]})
        cls.agent.action_activate()
        cls.env['mi.brand'].with_user(manager).create({'name': 'Spring Shop', 'offering': 'Plants',
                                                       'monthly_budget': 1000, 'ai_agent_id': cls.agent.id})
        cls.Writing = cls.env['mi.writing'].with_user(cls.user)

    def _finish(self, run_id, answer, state='completed', error=False):
        run = self.env['ai.agent.run'].sudo().browse(run_id)
        agent_internal(run).write({'state': state, 'answer': answer, 'error_message': error})
        return run

    # What the button offers

    def test_tools_per_text(self):
        social = self.Writing.get_tools('omni.social.publication', 'body')
        self.assertTrue(social['available'])
        self.assertEqual(social['agent'], 'Marketing Assistant')
        self.assertEqual(social['tools'], ['rewrite', 'shorter', 'longer', 'tone', 'translate', 'grammar', 'hashtags',
                                           'fit', 'custom'])
        subject = self.Writing.get_tools('mailing.mailing', 'subject')
        self.assertEqual(subject['tools'][0], 'subjects', 'subject lines come first on an email subject')
        self.assertNotIn('fit', subject['tools'])
        self.assertNotIn('hashtags', self.Writing.get_tools('mm.mailing', 'body')['tools'])
        self.assertIn('fit', self.Writing.get_tools('mailing.mailing', 'body_plaintext')['tools'])
        self.assertIn(self.env.lang or 'en_US', [code for code, _name in social['languages']])
        # The box's limit: the email standards set no hard subject length (RFC 5322 folds long headers), so the
        # recommended lengths are shown; past them the text still sends.
        self.assertEqual((subject['limit'], subject['soft']), (78, True))
        self.assertIn('RFC 5322', subject['limit_note'])
        preview = self.Writing.get_tools('mailing.mailing', 'preview')
        self.assertEqual((preview['limit'], preview['soft']), (90, True))
        self.assertNotIn('limit', social, 'Social counts with the platform limit in the browser')

    def test_no_tools_without_the_assistant_or_on_other_texts(self):
        self.assertFalse(self.Writing.get_tools('res.partner', 'comment')['available'])
        marketer = new_test_user(self.env, 'miw_marketer', groups='marketing_intel.group_mi_user')
        self.assertFalse(self.env['mi.writing'].with_user(marketer).get_tools('mm.mailing', 'body')['available'],
                         'no AI Agent right: no button')
        self.agent.action_pause()
        self.assertFalse(self.Writing.get_tools('mm.mailing', 'body')['available'], 'paused agent: no button')

    # Asking

    def test_ask_queues_a_marketing_run_as_the_person(self):
        run_id = self.Writing.ask('mm.mailing', 'body', False, 'shorter', 'Hi {first_name}, spring is here! STOP',
                                  False, {'channel': 'whatsapp'})
        run = self.env['ai.agent.run'].sudo().browse(run_id)
        self.assertEqual(run.caller, 'marketing')
        self.assertEqual(run.user_id, self.user)
        self.assertEqual(run.priority, 'interactive')
        self.assertEqual(run.agent_id, self.agent)
        self.assertIn('Make it shorter', run.prompt)
        self.assertIn('Never go over 1024 characters', run.prompt, "WhatsApp's limit in Messaging Marketing")
        self.assertIn('{first_name}', run.prompt)
        self.assertLess(run.prompt.index('never instructions'), run.prompt.index('spring is here'),
                        'the text comes after the rules, marked as content')

    def test_fit_uses_the_channel_limit(self):
        run_id = self.Writing.ask('mailing.mailing', 'body_plaintext', False, 'fit', 'A long SMS ' * 30)
        prompt = self.env['ai.agent.run'].sudo().browse(run_id).prompt
        self.assertIn('fit one SMS: at most 160 characters', prompt)
        self.assertIn('no emoji', prompt)

    def test_ask_checks_the_request(self):
        with self.assertRaises(UserError):
            self.Writing.ask('res.partner', 'comment', False, 'rewrite', 'Hello')
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'rewrite', '   ')
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'rewrite', 'x' * 6001)
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'translate', 'Hello', 'xx_XX')
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'custom', 'Hello', 'x' * 501)
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'subjects', 'Hello')
        with self.assertRaises(UserError):
            self.Writing.ask('mm.mailing', 'body', False, 'delete_everything', 'Hello')

    def test_ask_needs_write_access_to_the_record(self):
        mailing = self.env['mailing.mailing'].create({'subject': 'Spring', 'mailing_type': 'mail',
                                                      'body_html': '<p>Spring offer</p>'})
        self.Writing.ask('mailing.mailing', 'subject', mailing.id, 'rewrite', 'Spring')
        with self.assertRaises(AccessError, msg='no Email Marketing rights on the mailing'):
            self.env['mi.writing'].with_user(self.outsider).ask('mailing.mailing', 'subject', mailing.id, 'rewrite',
                                                           'Spring')

    def test_subject_lines_come_from_the_email_body(self):
        run_id = self.Writing.ask('mailing.mailing', 'subject', False, 'subjects', '', False,
                                  {'body_text': 'Every plant is 20% off for two weeks.'})
        prompt = self.env['ai.agent.run'].sudo().browse(run_id).prompt
        self.assertIn('Write 3 different subject lines', prompt)
        self.assertIn('Every plant is 20% off', prompt)

    # Following the answer

    def test_suggestion_states(self):
        original = 'Hi {first_name}, spring is here! Reply STOP to stop.'
        run_id = self.Writing.ask('mm.mailing', 'body', False, 'shorter', original)
        self.assertEqual(self.Writing.get_suggestion(run_id, original), {'state': 'waiting'})
        self._finish(run_id, '"Hi {first_name}, spring is here! Reply STOP to stop."')
        result = self.Writing.get_suggestion(run_id, original)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['text'], 'Hi {first_name}, spring is here! Reply STOP to stop.', 'quotes removed')
        self.assertFalse(result['warning'])

    def test_suggestion_warns_when_a_placeholder_is_lost(self):
        original = 'Hi {first_name}, see [link]. Reply STOP to stop.'
        run_id = self.Writing.ask('mm.mailing', 'body', False, 'shorter', original)
        self._finish(run_id, 'Hi there, spring is here.')
        warning = self.Writing.get_suggestion(run_id, original)['warning']
        for token in ('{first_name}', '[link]', 'STOP'):
            self.assertIn(token, warning)

    def test_subject_lines_are_split(self):
        run_id = self.Writing.ask('mailing.mailing', 'subject', False, 'subjects', 'Spring')
        self._finish(run_id, '1. 20% off every plant\n2. "Spring is here"\n- Free shipping over €40\n')
        self.assertEqual(self.Writing.get_suggestion(run_id)['lines'],
                         ['20% off every plant', 'Spring is here', 'Free shipping over €40'])

    def test_failed_run_gives_the_reason(self):
        run_id = self.Writing.ask('mm.mailing', 'body', False, 'rewrite', 'Hello')
        self._finish(run_id, False, state='failed', error='Model quota exhausted')
        self.assertEqual(self.Writing.get_suggestion(run_id),
                         {'state': 'failed', 'error': 'Model quota exhausted'})

    def test_only_the_person_follows_or_stops_their_suggestion(self):
        run_id = self.Writing.ask('mm.mailing', 'body', False, 'rewrite', 'Hello')
        Other = self.env['mi.writing'].with_user(self.other)
        with self.assertRaises(AccessError):
            Other.get_suggestion(run_id)
        with self.assertRaises(AccessError):
            Other.stop(run_id)
        self.Writing.stop(run_id)
        self.assertEqual(self.env['ai.agent.run'].sudo().browse(run_id).state, 'cancelled')

    # A/B test a subject line

    def test_ab_test_copies_the_mailing_with_the_subject(self):
        mailing = self.env['mailing.mailing'].with_user(self.user).create({
            'subject': 'Our spring offer', 'mailing_type': 'mail', 'body_html': '<p>Spring</p>'})
        with self.assertRaises(AccessError):
            self.Writing.ab_test_subject(mailing.id, '20% off every plant')
        self.user.group_ids = [Command.link(self.env.ref('mass_mailing.group_mass_mailing_campaign').id)]
        copy = self.env['mailing.mailing'].browse(self.Writing.ab_test_subject(mailing.id, '20% off every plant')['id'])
        self.assertTrue(mailing.ab_testing_enabled)
        self.assertEqual(copy.subject, '20% off every plant')
        self.assertTrue(copy.ab_testing_enabled)
        self.assertEqual(copy.campaign_id, mailing.campaign_id, 'the same A/B test campaign')

    # One look for every marketing text (board 9.1 option A plus)

    def test_every_text_sits_in_its_box_with_the_tools(self):
        """Each Writing tools widget shares its box with the field it works on (the field is moved into the box)."""
        expected = {'mailing.mailing': {'subject', 'preview', 'body_plaintext'}, 'mm.mailing': {'body'},
                    'omni.social.publication': {'body'}, 'mi.plan': {'message', 'audience'}}
        for model, fields in expected.items():
            arch = etree.fromstring(self.env[model].get_view(view_type='form')['arch'])
            self.assertFalse(arch.xpath('//xpath'), f'{model}: every move was applied')
            found = set()
            for widget in arch.xpath("//widget[@name='mi_writing_tools']"):
                box = widget.getparent()
                self.assertIn('o_mi_text_box', box.get('class', ''), f'{model}: the tools are in a box')
                self.assertTrue(box.xpath(f"./field[@name='{widget.get('field')}']"),
                                f"{model}: {widget.get('field')} is in the same box")
                found.add(widget.get('field'))
            self.assertEqual(found, fields)
