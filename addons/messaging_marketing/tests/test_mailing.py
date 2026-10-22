import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.messaging_marketing.models.inbound import is_stop
from odoo.addons.messaging_marketing.models.mailing import Mailing, render
from odoo.addons.omni_channel.models.command import internal as omni_internal
from odoo.addons.omni_channel.providers.base import HealthResult
from odoo.addons.omni_channel.providers.dispatch import DispatchResult, dispatch_claim
from odoo.addons.omni_channel.providers.inbound import InboundEvent


class Adapter:
    """Mock connector: healthy, can send, and receives verified test webhooks."""
    dispatch_supported = True
    inbound_release_ready = True
    result = DispatchResult('accepted', provider_message_key='wa-msg-1')

    def check_sender_health(self, config):
        return HealthResult(True, config['namespace'], config['account_key'], config['sender_key'])

    def validate_command(self, payload, config):
        return payload['operation'] == 'message.send'

    def dispatch(self, claim):
        return self.result

    def verify_request(self, raw, headers, config):
        return headers.get('X-Test-Signature') == 'verified'

    def normalize(self, value, config):
        return tuple(InboundEvent(**row) for row in value['events'])

    def check_endpoint(self, config):
        return True


@tagged('post_install', '-at_install')
class TestMailing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.env.company.country_id = cls.env.ref('base.my')
        cls.marketer = new_test_user(cls.env, 'mmm_marketer', groups='messaging_marketing.group_mm_user')
        cls.approver = new_test_user(
            cls.env, 'mmm_approver',
            groups='messaging_marketing.group_mm_user,approval_center.group_approval_center_approver')
        cls.manager = new_test_user(
            cls.env, 'mmm_manager', groups='omni_channel.group_omni_manager,messaging_marketing.group_mm_manager')
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Marketing QA', 'code': 'mm_qa',
            'user_ids': [fields.Command.set([cls.marketer.id, cls.approver.id, cls.manager.id])]})
        cls.policy = cls.env['approval.center.policy'].create({
            'name': 'Marketing messages', 'company_id': cls.env.company.id,
            'approver_ids': [fields.Command.create({'user_id': cls.approver.id, 'required': True})]})
        wa = cls.env.ref('omni_channel.channel_type_whatsapp')
        cls.channel = cls.env['omni.channel'].create({
            'name': 'Shop WhatsApp', 'purpose_id': cls.team.id, 'channel_type_id': wa.id,
            'approval_type_id': cls.policy.id})
        cls.account = cls.env['omni.account'].create({
            'name': 'Shop number', 'purpose_id': cls.team.id, 'channel_type_id': wa.id,
            'external_account_key': 'wa-1', 'namespace': 'wa-1', 'credential_reference': 'OMNI_SECRET_MM_TEST'})
        cls.sender = cls.env['omni.outbound.sender'].create({
            'name': 'Shop sender', 'channel_id': cls.channel.id, 'account_id': cls.account.id,
            'external_key': 'wa-1'})
        Contact = cls.env['mm.contact']
        cls.aisha = Contact.create({'name': 'Aisha Rahman', 'whatsapp': '+60 19 555 0001'})
        cls.ben = Contact.create({'name': 'Ben', 'whatsapp': '+60 19 555 0002'})  # never answered
        cls.chen = Contact.create({'name': 'Chen', 'whatsapp': '+60 19 555 0003'})
        cls.dina = Contact.create({'name': 'Dina', 'whatsapp': '+60 19 555 0004'})
        cls.eve = Contact.create({'name': 'Eve'})  # no number
        for contact in cls.aisha | cls.chen | cls.dina:
            contact._record_consent('whatsapp', 'opt_in', 'form', 'Website sign-up form, offers box ticked')
        cls.chen._record_consent('whatsapp', 'opt_out', 'keyword', '')
        cls.env['mm.blacklist'].create({'channel': 'whatsapp', 'address': '+60195550004'})
        cls.list = cls.env['mm.list'].create({'name': 'VIP', 'purpose_id': cls.team.id})
        cls.env['mm.subscription'].create([{'list_id': cls.list.id, 'contact_id': c.id}
                                           for c in cls.aisha | cls.ben | cls.chen | cls.dina | cls.eve])

    def setUp(self):
        super().setUp()
        self.adapter = Adapter()
        for target in ('odoo.addons.omni_channel.models.foundation.get_adapter',
                       'odoo.addons.omni_channel.providers.dispatch.get_adapter',
                       'odoo.addons.omni_channel.models.inbox.get_adapter',
                       'odoo.addons.omni_channel.providers.inbound.get_adapter'):
            patcher = patch(target, return_value=self.adapter)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(Mailing, '_connector_sends', lambda self, code: True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sender.with_user(self.manager).action_activate(self.channel.generation)
        omni_internal(self.channel).write({'dispatch_enabled': True})

    def _mailing(self, **values):
        return self.env['mm.mailing'].with_user(self.marketer).create(dict({
            'name': 'Ramadan offer', 'channel': 'whatsapp', 'channel_id': self.channel.id,
            'purpose_id': self.team.id, 'list_ids': [fields.Command.set(self.list.ids)],
            'body': 'Hi {first_name}, 20% off until Sunday. Reply STOP to stop.',
            'reason': 'Monthly offer for VIP customers', 'price_per_message': 0.25}, **values))

    def _approve(self, mailing):
        mailing.action_submit()
        mailing.approval_request_id.with_user(self.approver).action_approve()

    def _dispatch_all(self):
        Command = self.env['omni.command'].sudo()
        while True:
            claim = Command._claim_next()
            if claim is None:
                return
            if claim is False:
                continue
            Command.browse(claim.command_id)._finish_attempt(claim, dispatch_claim(claim))
            omni_internal(self.channel).write({'next_dispatch_at': False})

    def test_audience_counts_and_preview(self):
        mailing = self._mailing()
        self.assertEqual(mailing.member_count, 5)
        self.assertEqual(mailing.audience_count, 1)
        self.assertEqual((mailing.excluded_no_answer, mailing.excluded_opted_out, mailing.excluded_blacklisted,
                          mailing.excluded_no_address), (1, 1, 1, 1))
        self.assertEqual(mailing.cost_estimate, 0.25)
        self.assertEqual(mailing.excluded_summary,
                         'Out of 5 list members. Not included: 1 without an opt-in yet, 1 opted out, '
                         '1 blacklisted, 1 without an address on this channel.')
        self.assertIn('Hi ', mailing.preview_text)
        self.assertNotIn('{first_name}', mailing.preview_text)
        self.assertEqual(mailing.char_limit, 1024)
        self.assertEqual(render('Hello {first_name} / {name}', self.aisha), 'Hello Aisha / Aisha Rahman')

    def test_submit_freezes_and_needs_a_complete_draft(self):
        incomplete = self._mailing(reason=False, body='')
        with self.assertRaisesRegex(UserError, 'Write the message'):
            incomplete.action_submit()
        mailing = self._mailing()
        mailing.action_submit()
        self.assertEqual(mailing.state, 'pending')
        self.assertEqual(mailing.payload['recipients'], [[self.aisha.id, '+60195550001']])
        request = mailing.approval_request_id
        self.assertEqual(request.mm_audience_count, 1)
        self.assertIn('Hi Aisha', request.mm_preview)
        self.assertIn('1 no opt-in yet', request.mm_excluded)
        self.assertEqual(request.mm_cost, '0.25 ' + mailing.currency_id.name)
        with self.assertRaises(AccessError):
            mailing.write({'body': 'Changed after review'})
        with self.assertRaises(AccessError):
            mailing.unlink()
        with self.assertRaises(AccessError):
            request.with_user(self.marketer).write({'reason': 'forged'})
        with self.assertRaises(AccessError):  # nobody approves their own mailing
            request.with_user(self.marketer).action_approve()

    def test_approval_sends_through_omnichannel(self):
        mailing = self._mailing()
        self._approve(mailing)
        self.assertEqual(mailing.state, 'sending')
        trace = mailing.trace_ids
        self.assertEqual(len(trace), 1)
        self.assertEqual((trace.state, trace.address), ('queued', '+60195550001'))
        command = trace.command_id
        self.assertEqual(command.body, 'Hi Aisha, 20% off until Sunday. Reply STOP to stop.')
        self.assertEqual(command.approval_request_id, mailing.approval_request_id)
        self.assertEqual(command.payload['recipient'], '+60195550001')
        self._dispatch_all()
        self.assertEqual(command.state, 'accepted')
        self.assertEqual(trace.state, 'sent')
        self.assertTrue(trace.sent_at)
        self.assertEqual(mailing.state, 'done')
        self.assertEqual((mailing.recipient_count, mailing.sent_count, mailing.failed_count), (1, 1, 0))

    def test_opt_out_after_approval_stops_the_message(self):
        mailing = self._mailing(schedule='later', scheduled_at=fields.Datetime.now() + timedelta(hours=1))
        self._approve(mailing)
        self.assertEqual(mailing.state, 'approved')
        self.assertEqual(mailing.display_state, 'Scheduled')
        self.aisha._record_consent('whatsapp', 'opt_out', 'customer_request', '')
        with patch('odoo.addons.messaging_marketing.models.mailing.fields.Datetime.now',
                   return_value=fields.Datetime.now() + timedelta(hours=2)):
            self.env['mm.mailing']._cron_send_scheduled()
        self.assertEqual(mailing.state, 'done')
        self.assertEqual(mailing.trace_ids.state, 'skipped')
        self.assertIn('opted out', mailing.trace_ids.note)
        self.assertFalse(self.env['omni.command'].sudo().search([('mm_trace_id', 'in', mailing.trace_ids.ids)]))

    def test_dispatch_rechecks_opt_in_just_before_sending(self):
        mailing = self._mailing()
        self._approve(mailing)
        trace = mailing.trace_ids
        self.env['mm.blacklist'].create({'channel': 'whatsapp', 'address': '+60195550001'})
        self._dispatch_all()
        self.assertEqual(trace.command_id.state, 'held')
        self.assertEqual(trace.state, 'held')
        self.assertEqual(mailing.state, 'done')

    def test_commands_cannot_borrow_a_mailing_approval(self):
        mailing = self._mailing()
        self._approve(mailing)
        with self.assertRaises(AccessError):
            self.env['omni.command'].with_user(self.marketer).create({
                'channel_id': self.channel.id, 'recipient': '+60195550002', 'body': 'Not approved',
                'reason': 'x', 'mm_trace_id': mailing.trace_ids.id})
        command = mailing.trace_ids.command_id.sudo()
        other = self._mailing(name='Other')
        other.action_submit()
        self.assertFalse(command._approval_targets_command(other.approval_request_id.sudo()))
        self.assertTrue(command._approval_targets_command(mailing.approval_request_id.sudo()))

    def test_refuse_and_cancel(self):
        mailing = self._mailing()
        mailing.action_submit()
        mailing.approval_request_id.with_user(self.approver).action_refuse()
        self.assertEqual(mailing.state, 'refused')
        self.assertFalse(mailing.trace_ids)
        draft = self._mailing(name='Withdrawn')
        draft.action_submit()
        draft.action_cancel()
        self.assertEqual((draft.state, draft.approval_request_id.state), ('cancelled', 'refused'))
        copy = draft.action_duplicate()
        self.assertEqual(self.env['mm.mailing'].browse(copy['res_id']).state, 'draft')

    def test_cancel_while_sending_withdraws_queued_messages(self):
        mailing = self._mailing()
        self._approve(mailing)
        mailing.action_cancel()
        self.assertEqual(mailing.trace_ids.state, 'cancelled')
        self.assertEqual(mailing.trace_ids.command_id.state, 'cancelled')

    def test_channel_problems_are_explained(self):
        mailing = self._mailing(channel_id=False)
        self.assertIn('Choose the WhatsApp channel', mailing.channel_problem)
        with patch.object(Mailing, '_connector_sends', lambda self, code: False):
            mailing.invalidate_recordset(['channel_problem'])
            self.assertIn('not available yet', mailing.channel_problem)
            with self.assertRaisesRegex(UserError, 'not available yet'):
                self._mailing().action_submit()
        omni_internal(self.channel).write({'dispatch_enabled': False})
        paused = self._mailing(name='Paused')
        self.assertIn('Sending is paused', paused.channel_problem)
        paused.action_submit()  # approval can go ahead; messages wait for sending to be enabled

    def test_failed_delivery_is_explained(self):
        self.adapter.result = DispatchResult('definitely_not_sent', reason_code='invalid_recipient')
        mailing = self._mailing()
        self._approve(mailing)
        self._dispatch_all()
        self.assertEqual(mailing.trace_ids.state, 'failed')
        self.assertIn('blocked', mailing.trace_ids.note)
        self.assertEqual(self.sender.health, 'healthy', 'One refused recipient does not break the sender')

    def test_stop_reply_opts_out(self):
        self.assertTrue(is_stop(' stop! '))
        self.assertTrue(is_stop('Unsubscribe'))
        self.assertFalse(is_stop('please stop by the shop'))
        Endpoint = type(self.env['omni.inbound.endpoint'])
        if hasattr(Endpoint, '_whatsapp_verified'):  # omni_whatsapp: the Meta callback is verified in this test
            patcher = patch.object(Endpoint, '_whatsapp_verified', lambda self: True)
            patcher.start()
            self.addCleanup(patcher.stop)
        endpoint = self.env['omni.inbound.endpoint'].create({
            'name': 'Shop inbox', 'channel_id': self.channel.id, 'account_id': self.account.id,
            'external_key': 'wa-1'})
        policy = self.env['omni.inbound.policy'].create({'name': 'Text intake', 'channel_id': self.channel.id})
        policy.with_user(self.manager).action_activate()
        endpoint.with_user(self.manager).action_enable()
        endpoint._receive(json.dumps({'events': [{
            'event_key': 'evt-stop', 'endpoint_key': 'wa-1', 'namespace': 'wa-1', 'kind': 'message',
            'sender_key': '60195550001', 'thread_key': '60195550001', 'message_key': 'm-stop', 'body': 'STOP',
            'occurred_at': fields.Datetime.to_string(fields.Datetime.now() - timedelta(minutes=1)), 'revision': 0, 'private': True}]}).encode(),
            {'X-Test-Signature': 'verified'})
        self.env['omni.webhook.event']._process_batch()
        self.assertEqual(self.aisha.whatsapp_status, 'opted_out')
        consent = self.aisha.consent_ids[:1]
        self.assertEqual((consent.action, consent.source), ('opt_out', 'keyword'))
        self.assertIn('STOP', consent.evidence)
        conversation = self.env['omni.conversation'].search([('endpoint_id', '=', endpoint.id)])
        action = conversation.with_user(self.marketer).action_mm_add_contact()
        self.assertEqual(action['res_id'], self.aisha.id, 'The chat is linked to the existing contact')
