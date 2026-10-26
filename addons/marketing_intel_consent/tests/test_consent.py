from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestConsent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.user = new_test_user(cls.env, 'mic_user', groups='marketing_intel.group_mi_user,messaging_marketing.group_mm_user')
        cls.approver = new_test_user(cls.env, 'mic_approver', groups='marketing_intel.group_mi_user,'
                                                                    'approval_center.group_approval_center_approver')
        cls.partner = cls.env['res.partner'].create({'name': 'Aisha Rahman', 'email': 'aisha@example.com'})
        cls.mm = cls.env['mm.contact'].create({'name': 'Aisha Rahman', 'whatsapp': '+60 19 555 0201',
                                               'partner_id': cls.partner.id})
        policy = cls.env.ref('marketing_intel_consent.policy_data_request')
        policy.write({'company_id': cls.env.company.id,
                      'approver_ids': [Command.clear(), Command.create({'user_id': cls.approver.id})]})

    def test_ledger_is_append_only_and_stops_email(self):
        subject = self.env['mi.consent.subject']._find_or_create(partner=self.partner)
        self.assertEqual(subject.email, 'aisha@example.com')
        subject._record('email', 'opt_out', 'staff', 'Asked by phone to stop emails')
        self.assertEqual(subject.email_status, 'opted_out')
        self.assertTrue(self.env['mail.blacklist'].search([('email', '=', 'aisha@example.com')]),
                        'an email opt-out reaches the email blacklist')
        with self.assertRaises(AccessError):
            subject.record_ids.write({'evidence': 'changed'})
        with self.assertRaises(AccessError):
            subject.record_ids.unlink()
        with self.assertRaises(AccessError):
            self.env['mi.consent.record'].create({'subject_id': subject.id, 'channel': 'sms', 'action': 'opt_in',
                                                  'source': 'staff', 'evidence': 'forged'})
        with self.assertRaises(UserError):
            subject._record('sms', 'opt_in', 'staff', 'yes')

    def test_two_way_sync_with_messaging_and_blacklists(self):
        self.mm._record_consent('whatsapp', 'opt_in', 'form', 'Website form, WhatsApp offers ticked')
        subject = self.env['mi.consent.subject']._find_or_create(partner=self.partner)
        self.assertEqual(subject.whatsapp_status, 'opted_in', 'Messaging consents come into the ledger')
        subject._record('whatsapp', 'opt_out', 'preference_page', 'Unticked WhatsApp on the page')
        self.assertEqual(self.mm.whatsapp_status, 'opted_out', 'ledger opt-outs reach Messaging')
        self.env['mail.blacklist']._add('bob@example.com', message='Unsubscribed from the newsletter')
        bob = self.env['mi.consent.subject'].search([('email', '=', 'bob@example.com')])
        self.assertEqual(bob.email_status, 'opted_out', 'unsubscribe links come into the ledger')
        self.assertEqual(bob.record_ids.source, 'unsubscribe')

    def test_preference_page_choices(self):
        subject = self.env['mi.consent.subject']._find_or_create(partner=self.partner)
        offers = self.env.ref('marketing_intel_consent.topic_offers')
        subject._apply_preferences(['email', 'sms'], [offers.id], 'Preference page from 10.0.0.1')
        self.assertEqual((subject.email_status, subject.sms_status), ('opted_in', 'opted_in'))
        self.assertIn(offers, subject.topic_ids)
        before = len(subject.record_ids)
        subject._apply_preferences(['email', 'sms'], [offers.id], 'same again')
        self.assertEqual(len(subject.record_ids), before, 'only changes are recorded')
        subject._apply_preferences([], [], 'Unsubscribe from everything', unsubscribe_all=True)
        self.assertTrue(all(subject[f'{c}_status'] == 'opted_out'
                            for c in ('email', 'sms', 'whatsapp', 'telegram', 'social')))
        self.assertFalse(subject.topic_ids)

    def test_data_requests_need_approval(self):
        subject = self.env['mi.consent.subject']._find_or_create(partner=self.partner)
        subject._record('email', 'opt_in', 'form', 'Newsletter form on the website')
        Request = self.env['mi.data.request'].with_user(self.user)
        export = Request.create({'subject_id': subject.id, 'kind': 'export', 'note': 'Email of 3 March, ID checked'})
        with self.assertRaises(AccessError):
            export.action_execute()
        export.action_submit()
        self.assertEqual(export.state, 'pending')
        export.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(export.state, 'done')
        self.assertTrue(export.attachment_id)
        erase = Request.create({'subject_id': subject.id, 'kind': 'erase', 'note': 'Asked by email, ID checked'})
        erase.action_submit()
        erase.approval_request_id.with_user(self.approver).action_approve()
        self.assertTrue(subject.erased)
        self.assertNotIn('Aisha', subject.name)
        self.assertFalse(self.mm.active)
        self.assertEqual(subject.email_status, 'opted_out')
        self.assertTrue(subject.record_ids, 'the history is kept as proof')


@tagged('post_install', '-at_install')
class TestPreferencePage(HttpCase):
    def test_page_opens_and_saves(self):
        subject = self.env['mi.consent.subject']._find_or_create(email='page@example.com', name='Page Person')
        token = subject.sudo().token
        response = self.url_open('/marketing/preferences/%s' % token)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Your preferences', response.text)
        self.assertIn('WhatsApp', response.text, 'channel names are shown')
        self.assertIn('Offers and promotions', response.text)
        self.assertEqual(self.url_open('/marketing/preferences/not-a-valid-token-at-all').status_code, 404)
