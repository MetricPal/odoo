from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal as social_internal
from odoo.addons.omni_social.providers import registry


@tagged('post_install', '-at_install')
class TestContentCalendar(TransactionCase):
    """Content calendar, plan M7 (approved boards 14.1 and 14.2)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        groups = ('marketing_intel.group_mi_user,mass_mailing.group_mass_mailing_user,'
                  'messaging_marketing.group_mm_user,omni_channel.group_omni_user')
        cls.marketer = new_test_user(cls.env, 'calendar_marketer', groups=groups)
        cls.other = new_test_user(cls.env, 'calendar_other', groups=groups)
        cls.reader = new_test_user(cls.env, 'calendar_reader', groups='marketing_intel.group_mi_user')
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Calendar QA', 'code': 'calendar_qa', 'user_ids': [Command.set(cls.marketer.ids)]})
        cls.soon = fields.Datetime.now().replace(microsecond=0) + timedelta(days=3)
        cls.later = cls.soon + timedelta(days=2)
        cls.Content = cls.env['mi.content']
        Mailing = cls.env['mailing.mailing'].with_user(cls.marketer)
        model = cls.env.ref('mass_mailing.model_mailing_list').id
        cls.email = Mailing.create({'subject': 'Black Friday', 'mailing_type': 'mail', 'mailing_model_id': model,
                                    'schedule_type': 'scheduled', 'schedule_date': cls.soon})
        cls.sms = Mailing.create({'subject': 'Last seats', 'mailing_type': 'sms', 'mailing_model_id': model,
                                  'body_plaintext': 'Two seats left. Reply STOP to opt out.'})
        cls.channel = cls.env['omni.channel'].create({
            'name': 'Shop WhatsApp', 'purpose_id': cls.team.id,
            'channel_type_id': cls.env.ref('omni_channel.channel_type_whatsapp').id})
        cls.message = cls.env['mm.mailing'].with_user(cls.marketer).create({
            'name': 'Early access', 'channel': 'whatsapp', 'channel_id': cls.channel.id,
            'purpose_id': cls.team.id, 'body': 'Hi {first_name}, early access starts now.',
            'reason': 'Monthly offer', 'schedule': 'later', 'scheduled_at': cls.soon})

    def _item(self, record, user=None):
        self.env.flush_all()
        return self.Content.with_user(user or self.marketer).search(
            [('res_model', '=', record._name), ('res_id', '=', record.id)])

    def _set_state(self, record, state):
        self.env.flush_all()
        self.env.cr.execute('UPDATE %s SET state = %%s WHERE id = %%s' % record._table, [state, record.id])  # noqa: S608
        self.env.invalidate_all()

    # ------------------------------------------------------------------ what the calendar shows

    def test_items_of_every_channel(self):
        email, sms, message = self._item(self.email), self._item(self.sms), self._item(self.message)
        self.assertEqual((email.channel_id.code, email.display_name, email.date, email.status),
                         ('email', 'Email · Black Friday', self.soon, 'draft'))
        self.assertTrue(email.is_hatched, 'A draft with a planned time shows dashed')
        self.assertEqual((email.status_label, email.user_id), ('Draft', self.marketer))
        self.assertEqual((sms.channel_id.code, sms.date, sms.no_time), ('sms', False, 'No time yet'))
        self.assertIn('Two seats left', sms.text)
        self.assertEqual((message.channel_id.code, message.date, message.status_label),
                         ('messaging', self.soon, 'Draft'))
        self.assertIn('Shop WhatsApp', message.where)
        self._set_state(self.message, 'pending')
        self.assertEqual(self._item(self.message).status, 'review')
        self._set_state(self.email, 'done')
        email = self._item(self.email)
        self.assertEqual((email.status, email.is_striked, email.status_label), ('sent', True, 'Sent'))
        self._set_state(self.message, 'cancelled')
        self.assertFalse(self._item(self.message), 'Cancelled items are not content any more')

    def test_only_what_the_person_may_read_in_each_app(self):
        self.assertFalse(self.Content.with_user(self.reader).search([]),
                         'Without access to the apps there is nothing to see')
        self.assertFalse(self.Content.with_user(self.reader)._read_group([], ['channel_id'], ['__count']))
        self.assertTrue(self._item(self.email, self.other), 'Email Marketing users read every mailing')
        self.assertFalse(self._item(self.message, self.other), "Not in the message's communication team")
        groups = dict(self.Content.with_user(self.marketer)._read_group(
            [('res_id', 'in', (self.email | self.sms).ids), ('res_model', '=', 'mailing.mailing')],
            ['channel_id'], ['__count']))
        self.assertEqual(sorted(channel.code for channel in groups), ['email', 'sms'])

    def test_campaign_of_an_item(self):
        brand = self.env['mi.brand'].create({'name': 'Calendar brand'})
        plan = self.env['mi.plan'].create({'name': 'Black Friday 2026', 'brand_id': brand.id})
        self.env['mi.plan.item'].create({'plan_id': plan.id, 'channel': 'email'})
        self.env.flush_all()
        self.env.cr.execute("UPDATE mi_plan_item SET res_model = 'mailing.mailing', res_id = %s WHERE plan_id = %s",
                            [self.email.id, plan.id])
        self.env.invalidate_all()
        self.assertEqual(self._item(self.email).plan_id, plan)
        self.assertFalse(self._item(self.sms).plan_id)

    def test_open_and_new(self):
        action = self._item(self.sms).action_open()
        self.assertEqual((action['res_model'], action['res_id']), ('mailing.mailing', self.sms.id))
        self.assertTrue(action['context']['mailing_sms'])
        Content = self.Content.with_user(self.marketer)
        self.assertEqual([key for key, _label in Content.new_options()], ['email', 'sms', 'messaging', 'social'])
        when = fields.Datetime.to_string(self.soon)
        email = Content.action_new('email', when)
        self.assertEqual((email['res_model'], email['context']['default_calendar_date']), ('mailing.mailing', when))
        message = Content.action_new('messaging', when)
        self.assertEqual(message['context'], {'default_schedule': 'later', 'default_scheduled_at': when})
        past = Content.action_new('social', fields.Datetime.to_string(self.soon - timedelta(days=30)))
        self.assertEqual(past['context'], {}, 'A day that is past fills no time in')
        self.assertFalse(self.Content.with_user(self.reader).new_options())
        with self.assertRaises(UserError):
            self.Content.with_user(self.reader).action_new('email', when)

    # ------------------------------------------------------------------ dragging (board 14.2 B)

    def test_a_draft_and_a_queued_mailing_move(self):
        item = self._item(self.email)
        item.write({'date': self.later})
        self.assertEqual((self.email.schedule_date, self.email.state), (self.later, 'draft'))
        self.assertEqual(self._item(self.email).date, self.later)
        self._item(self.sms).write({'date': self.soon})
        self.assertEqual((self.sms.schedule_type, self.sms.schedule_date), ('scheduled', self.soon))
        self._set_state(self.email, 'in_queue')
        item = self._item(self.email)
        self.assertEqual(item.status, 'scheduled')
        item.write({'date': self.soon})
        self.assertEqual((self.email.schedule_date, self.email.state), (self.soon, 'in_queue'))

    def test_what_does_not_move(self):
        item = self._item(self.email)
        with self.assertRaisesRegex(UserError, 'still to come'):
            item.write({'date': fields.Datetime.now() - timedelta(hours=1)})
        with self.assertRaisesRegex(UserError, 'only moves'):
            item.write({'name': 'Renamed'})
        self._set_state(self.email, 'done')
        with self.assertRaisesRegex(UserError, 'went out already'):
            self._item(self.email).write({'date': self.later})
        self.assertEqual(self.email.schedule_date, self.soon)

    def test_a_message_moves_only_as_its_own_draft(self):
        self._item(self.message).write({'date': self.later})
        self.assertEqual(self.message.scheduled_at, self.later)
        self.team.user_ids += self.other
        with self.assertRaisesRegex(UserError, 'Only the person who prepared a draft'):
            self._item(self.message, self.other).write({'date': self.soon})
        self._set_state(self.message, 'pending')
        with self.assertRaisesRegex(UserError, 'Waiting for review'):
            self._item(self.message).write({'date': self.soon})
        self._set_state(self.message, 'approved')
        with self.assertRaisesRegex(UserError, 'was approved with it'):
            self._item(self.message).write({'date': self.soon})
        self.assertEqual(self.message.scheduled_at, self.later, 'An approved time is never changed from the calendar')

    def test_a_social_post(self):
        installed = sorted(registry.installed(self.env), key=lambda name: name != 'instagram')
        if not installed:
            self.skipTest('Needs a social platform module')
        account = self.env['omni.social.connection'].create({
            'name': 'Calendar account', 'provider': installed[0], 'purpose_id': self.team.id})
        social_internal(account).write({'connected': True, 'profile_name': '@calendar'})
        post = self.env['omni.social.publication'].with_user(self.marketer).create({
            'name': 'Webinar speakers', 'connection_id': account.id, 'body': 'Meet the speakers.',
            'reason': 'Webinar', 'scheduled_at': self.soon})
        item = self._item(post)
        self.assertEqual((item.channel_id.code, item.date, item.status_label), ('social', self.soon, 'Draft'))
        self.assertIn('Calendar account', item.where)
        item.write({'date': self.later})
        self.assertEqual(post.scheduled_at, self.later)
        social_internal(post.sudo()).write({'state': 'approved'})
        item = self._item(post)
        self.assertEqual((item.status, item.status_label), ('scheduled', 'Scheduled'))
        with self.assertRaisesRegex(UserError, 'was approved with it'):
            item.write({'date': self.soon})
        reply = self.env['omni.social.publication'].with_user(self.marketer).create({
            'name': 'A reply', 'connection_id': account.id, 'body': 'Thanks!', 'reason': 'Reply',
            'operation': 'message'})
        self.assertFalse(self._item(reply), 'Replies are not planned content')
