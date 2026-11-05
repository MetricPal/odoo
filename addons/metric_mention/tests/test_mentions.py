from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestMentions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mei = new_test_user(cls.env, 'mention_mei', name='Mei Wongsakul', groups='base.group_user')
        cls.omar = new_test_user(cls.env, 'mention_omar', name='Omar Haddadin', groups='base.group_user')
        cls.author = new_test_user(cls.env, 'mention_author', name='Author Person',
                                   groups='base.group_user,base.group_partner_manager')
        cls.partner = cls.env['res.partner'].create({'name': 'Tan Holdings Mention'})
        cls.Digest = cls.env['metric.mention.digest']

    def _sms(self, body):
        return self.env['mail.message'].create({
            'model': 'res.partner', 'res_id': self.partner.id, 'message_type': 'sms', 'body': body,
            'author_id': self.author.partner_id.id,
        })

    def _digests(self, user):
        return self.Digest.search([('user_id', '=', user.id)])

    def test_same_sms_text_gives_one_notification_with_a_count(self):
        for _i in range(3):
            self._sms('Order ready, @Mei Wongsakul please call the customer')
        digest = self._digests(self.mei)
        self.assertEqual((len(digest), digest.count, digest.channel), (1, 3, 'sms'))
        self.assertIn('3 SMS messages today', str(digest.message_id.body))
        self.assertIn(self.mei.partner_id, digest.message_id.notification_ids.res_partner_id)
        self.assertEqual(self.env['mail.notification'].search_count([
            ('res_partner_id', '=', self.mei.partner_id), ('mail_message_id', '=', digest.message_id.id)]), 1)
        self._sms('Different text for @Mei Wongsakul')
        self.assertEqual(len(self._digests(self.mei)), 2, 'a different text is its own notification')
        self.assertFalse(self._digests(self.omar))

    def test_activity_note_mentions_notify_once(self):
        activity = self.partner.with_user(self.author).activity_schedule(
            'mail.mail_activity_data_todo', summary='Call back', user_id=self.omar.id,
            note='<p>Please ask @Mei Wongsakul for the price</p>')
        digest = self._digests(self.mei)
        self.assertEqual((len(digest), digest.channel, digest.res_id), (1, 'activity', self.partner.id))
        self.assertFalse(self._digests(self.omar), 'the assignee is already told by the assignment')
        activity.write({'note': '<p>Please ask @Mei Wongsakul for the price, today</p>'})
        self.assertEqual(len(self._digests(self.mei)), 1, 'editing the note does not notify again')

    def test_mention_links_are_understood(self):
        html = f'<p>Hi <a href="#" data-oe-model="res.partner" data-oe-id="{self.omar.partner_id.id}">@Omar</a></p>'
        self.assertEqual(self.Digest._mentioned_users(html), self.omar)
        self.assertEqual(self.Digest._mentioned_users('email me at a@b.com'), self.env['res.users'])

    def test_scan_reads_new_records_once(self):
        self.partner.comment = 'Customer asked for @Omar Haddadin on the phone'
        self.assertEqual(self.Digest._scan_model('res.partner', 'comment', 'omnichannel'), 1)
        self.assertEqual(self._digests(self.omar).channel, 'omnichannel')
        self.assertEqual(self.Digest._scan_model('res.partner', 'comment', 'omnichannel'), 0, 'already read')
        self.assertEqual(self.Digest._scan_model('no.such.model', 'body', 'social'), 0)
