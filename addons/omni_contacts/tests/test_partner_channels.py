from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_channel.models.command import internal


@tagged('post_install', '-at_install')
class TestPartnerChannels(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.member = new_test_user(cls.env, 'pc_member', groups='omni_channel.group_omni_user,base.group_partner_manager')
        cls.outsider = new_test_user(cls.env, 'pc_outsider', groups='omni_channel.group_omni_user')
        cls.staff = new_test_user(cls.env, 'pc_staff', groups='base.group_user')
        cls.team = cls.env['omni.purpose'].create({'name': 'Care QA', 'code': 'pc_qa',
                                                  'user_ids': [fields.Command.set(cls.member.ids)]})
        cls.wa = cls.env.ref('omni_channel.channel_type_whatsapp')
        cls.ig = cls.env.ref('omni_channel.channel_type_instagram')
        cls.channel = cls.env['omni.channel'].create({'name': 'Care WhatsApp', 'purpose_id': cls.team.id,
                                                      'channel_type_id': cls.wa.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Aisha Rahman'})

    def _identity(self, key='60195550001'):
        return internal(self.env['omni.identity']).create({
            'channel_id': self.channel.id, 'namespace': 'wa-1', 'external_key': key})

    def test_linked_chat_appears_and_follows_the_link(self):
        identity = self._identity()
        self.assertFalse(self.partner.channel_type_ids)
        internal(identity).write({'partner_id': self.partner.id})
        row = self.partner.channel_ids
        self.assertEqual((row.source, row.handle, row.channel_type_id), ('conversation', '60195550001', self.wa))
        self.assertEqual(row.url, 'https://wa.me/60195550001')
        self.assertEqual(self.partner.channel_type_ids, self.wa)
        self.assertEqual(self.partner.active_channel_ids, row)
        internal(self.channel).write({'active': False})
        self.assertFalse(row.active)
        self.assertFalse(self.partner.channel_type_ids)
        internal(self.channel).write({'active': True})
        internal(identity).write({'partner_id': False})
        self.assertFalse(self.env['omni.partner.channel'].with_context(active_test=False).search(
            [('identity_id', '=', identity.id)]))

    def test_manual_profiles_and_urls(self):
        Channel = self.env['omni.partner.channel'].with_user(self.member)
        row = Channel.create({'partner_id': self.partner.id, 'channel_type_id': self.ig.id, 'handle': '@aisha.r'})
        self.assertEqual(row.url, 'https://www.instagram.com/aisha.r')
        self.assertEqual(self.partner.channel_type_ids, self.ig)
        row.handle = 'https://instagram.com/other'
        self.assertEqual(row.url, 'https://instagram.com/other')
        with self.assertRaises(AccessError):
            Channel.create({'partner_id': self.partner.id, 'channel_type_id': self.wa.id, 'handle': 'x',
                            'source': 'conversation'})
        with self.assertRaises(AccessError):
            self.env['omni.partner.channel'].with_user(self.staff).create(
                {'partner_id': self.partner.id, 'channel_type_id': self.ig.id, 'handle': 'nope'})

    def test_chat_identifiers_only_for_the_team(self):
        identity = self._identity('60195550009')
        internal(identity).write({'partner_id': self.partner.id})
        self.env['omni.partner.channel'].create({'partner_id': self.partner.id, 'channel_type_id': self.ig.id,
                                                 'handle': 'aisha'})
        partner = self.partner
        self.assertEqual(len(partner.with_user(self.member).channel_ids), 2)
        self.assertEqual(partner.with_user(self.outsider).channel_ids.mapped('source'), ['manual'])
        self.assertEqual(partner.with_user(self.staff).channel_ids.mapped('source'), ['manual'])
        # Tags show the platforms to everyone who can read the contact.
        self.assertEqual(set(partner.with_user(self.staff).channel_type_ids.mapped('code')), {'whatsapp', 'instagram'})
        conversation_row = partner.channel_ids.filtered(lambda r: r.source == 'conversation')
        with self.assertRaises(AccessError):
            conversation_row.with_user(self.member).write({'handle': 'changed'})

    def test_customers_filter_domain(self):
        customer = self.env['res.partner'].create({'name': 'Buyer', 'customer_rank': 1})
        found = self.env['res.partner'].search([('customer_rank', '>', 0), ('id', 'in', (customer | self.partner).ids)])
        self.assertEqual(found, customer)
