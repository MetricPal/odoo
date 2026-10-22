from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestAudience(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.country_id = cls.env.ref('base.my')
        cls.marketer = new_test_user(cls.env, 'mm_marketer', groups='messaging_marketing.group_mm_user')
        cls.admin = new_test_user(cls.env, 'mm_admin', groups='messaging_marketing.group_mm_manager')
        cls.team = cls.env.ref('omni_channel.purpose_marketing')
        cls.team.user_ids |= cls.marketer | cls.admin
        cls.Contact = cls.env['mm.contact'].with_user(cls.marketer)
        cls.aisha = cls.Contact.create({'name': 'Aisha', 'whatsapp': '019-555 0001'})

    def test_number_is_normalized_and_unique(self):
        self.assertEqual(self.aisha.whatsapp, '+60195550001')
        with self.assertRaises(ValidationError):
            self.Contact.create({'name': 'Bad', 'whatsapp': '12'})
        with self.assertRaises(Exception), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.Contact.create({'name': 'Twin', 'whatsapp': '+60 19-555 0001'})

    def test_status_follows_latest_evidence(self):
        self.assertEqual(self.aisha.whatsapp_status, 'unknown')
        self.assertFalse(self.aisha._can_receive('whatsapp'))
        with self.assertRaises(UserError):
            self.aisha._record_consent('whatsapp', 'opt_in', 'form', 'yes')  # too little evidence
        self.aisha._record_consent('whatsapp', 'opt_in', 'form', 'Website sign-up form, newsletter box ticked')
        self.assertEqual(self.aisha.whatsapp_status, 'opted_in')
        self.assertEqual(self.aisha.telegram_status, 'unknown')
        self.assertTrue(self.aisha._can_receive('whatsapp'))
        self.aisha._record_consent('whatsapp', 'opt_out', 'keyword', '')
        self.assertEqual(self.aisha.whatsapp_status, 'opted_out')
        self.assertFalse(self.aisha._can_receive('whatsapp'))
        self.assertEqual(len(self.aisha.consent_ids), 2)

    def test_telegram_opt_in_needs_a_chat(self):
        with self.assertRaises(UserError):
            self.aisha._record_consent('telegram', 'opt_in', 'message', 'Started the bot and pressed Subscribe')
        with self.assertRaises(AccessError):
            self.aisha.write({'telegram_chat': '123'})
        self.aisha.with_context(mm_telegram_link=True).write({'telegram_chat': '123'})
        self.aisha._record_consent('telegram', 'opt_in', 'message', 'Started the bot and pressed Subscribe')
        self.assertTrue(self.aisha._can_receive('telegram'))

    def test_evidence_is_immutable(self):
        consent = self.aisha._record_consent('whatsapp', 'opt_in', 'in_person', 'Signed the paper form at the shop')
        consent = consent.with_user(self.marketer)
        with self.assertRaises(AccessError):
            consent.write({'evidence': 'changed'})
        with self.assertRaises(AccessError):
            consent.unlink()
        with self.assertRaises(AccessError):
            self.env['mm.consent'].with_user(self.marketer).create({
                'contact_id': self.aisha.id, 'channel': 'whatsapp', 'action': 'opt_in', 'source': 'form',
                'evidence': 'forged evidence here'})
        with self.assertRaises(AccessError):
            consent.with_user(self.admin).unlink()

    def test_blacklist_wins_over_opt_in(self):
        self.aisha._record_consent('whatsapp', 'opt_in', 'form', 'Website sign-up form, newsletter box ticked')
        entry = self.env['mm.blacklist'].with_user(self.marketer).create(
            {'channel': 'whatsapp', 'address': '019 555 0001'})
        self.assertEqual(entry.address, '+60195550001')
        self.aisha.invalidate_recordset()
        self.assertTrue(self.aisha.whatsapp_blacklisted)
        self.assertFalse(self.aisha._can_receive('whatsapp'))
        self.assertIn(self.aisha, self.Contact.search([('whatsapp_blacklisted', '=', True)]))
        with self.assertRaises(AccessError):
            entry.unlink()
        entry.with_user(self.admin).unlink()
        self.aisha.invalidate_recordset()
        self.assertTrue(self.aisha._can_receive('whatsapp'))
        self.assertNotIn(self.aisha, self.Contact.search([('whatsapp_blacklisted', '=', True)]))

    def test_lists_counts_and_leaving(self):
        ben = self.Contact.create({'name': 'Ben', 'whatsapp': '+60 19 555 0002'})
        lst = self.env['mm.list'].with_user(self.marketer).create({'name': 'VIP'})
        self.assertEqual(lst.purpose_id, self.team)
        sub = self.env['mm.subscription'].with_user(self.marketer).create(
            [{'list_id': lst.id, 'contact_id': c.id} for c in self.aisha | ben])
        ben._record_consent('whatsapp', 'opt_in', 'form', 'Website sign-up form, newsletter box ticked')
        self.assertEqual((lst.contact_count, lst.whatsapp_count, lst.telegram_count), (2, 1, 0))
        self.assertEqual(self.Contact.search([('list_ids', 'in', lst.ids)]), self.aisha | ben)
        sub[1].opt_out = True
        self.assertTrue(sub[1].left_at)
        lst.invalidate_recordset()
        self.assertEqual((lst.contact_count, lst.whatsapp_count), (1, 0))
        new = self.Contact.with_context(mm_list_id=lst.id).create({'name': 'Chen'})
        self.assertIn(lst, new.list_ids)

    def test_list_needs_team_membership(self):
        outsider = new_test_user(self.env, 'mm_outsider', groups='messaging_marketing.group_mm_user')
        lst = self.env['mm.list'].with_user(self.marketer).create({'name': 'Team only'})
        self.assertFalse(self.env['mm.list'].with_user(outsider).search([('id', '=', lst.id)]))
        self.assertTrue(self.env['mm.contact'].with_user(outsider).search([('id', '=', self.aisha.id)]))

    def test_wizards(self):
        wizard = self.env['mm.consent.wizard'].with_user(self.marketer).create({
            'contact_ids': self.aisha.ids, 'channel': 'whatsapp', 'action': 'opt_in', 'source': 'import',
            'evidence': 'Consent column in the 2026 event sign-up sheet'})
        wizard.action_record()
        self.assertEqual(self.aisha.whatsapp_status, 'opted_in')
        partner = self.env['res.partner'].create({'name': 'Dina', 'phone': '+60 19 555 0003'})
        bad = self.env['res.partner'].create({'name': 'Eve', 'phone': '1'})
        lst = self.env['mm.list'].with_user(self.marketer).create({'name': 'Event'})
        result = self.env['mm.contact.import'].with_user(self.marketer).create({
            'partner_ids': (partner | bad).ids, 'list_id': lst.id}).action_import()
        dina = self.Contact.search([('partner_id', '=', partner.id)])
        self.assertEqual(dina.whatsapp, '+60195550003')
        self.assertEqual(dina.whatsapp_status, 'unknown', 'Adding a contact never opts it in')
        self.assertIn(lst, dina.list_ids)
        self.assertIn('Eve', result['params']['message'])
