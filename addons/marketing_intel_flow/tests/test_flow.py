from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.messaging_marketing.tests.test_mailing import Adapter
from odoo.addons.omni_channel.models.command import internal as omni_internal
from odoo.addons.omni_channel.providers.dispatch import dispatch_claim
from odoo.addons.omni_social.models.social import internal as social_internal
from odoo.addons.omni_social.providers import registry


@tagged('post_install', '-at_install')
class TestMarketingFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.env.company.country_id = cls.env.ref('base.my')
        groups = 'marketing_intel.group_mi_user,messaging_marketing.group_mm_user,omni_social.group_social_user'
        if not cls.env.ref('omni_social.group_social_user', raise_if_not_found=False):
            groups = 'marketing_intel.group_mi_user,messaging_marketing.group_mm_user'
        cls.marketer = new_test_user(cls.env, 'mif_marketer', groups=groups)
        cls.approver = new_test_user(cls.env, 'mif_approver', groups='marketing_intel.group_mi_user,'
                                                                     'approval_center.group_approval_center_approver')
        cls.manager = new_test_user(cls.env, 'mif_manager', groups='omni_channel.group_omni_manager')
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Marketing flows', 'code': 'mif_qa',
            'user_ids': [Command.set([cls.marketer.id, cls.approver.id, cls.manager.id])]})
        cls.policy = cls.env['approval.center.policy'].create({
            'name': 'WhatsApp messages', 'company_id': cls.env.company.id,
            'approver_ids': [Command.create({'user_id': cls.approver.id, 'required': True})]})
        wa = cls.env.ref('omni_channel.channel_type_whatsapp')
        cls.channel = cls.env['omni.channel'].create({
            'name': 'Brand WhatsApp', 'purpose_id': cls.team.id, 'channel_type_id': wa.id,
            'approval_type_id': cls.policy.id})
        account = cls.env['omni.account'].create({
            'name': 'Brand number', 'purpose_id': cls.team.id, 'channel_type_id': wa.id,
            'external_account_key': 'wa-f1', 'namespace': 'wa-f1', 'credential_reference': 'OMNI_SECRET_MIF_TEST'})
        cls.sender = cls.env['omni.outbound.sender'].create({
            'name': 'Brand sender', 'channel_id': cls.channel.id, 'account_id': account.id, 'external_key': 'wa-f1'})
        installed = registry.installed(cls.env)
        if not installed:
            cls.skipTest(cls, 'Needs a social platform module (Instagram, Facebook, LinkedIn...)')
        cls.provider = 'instagram' if 'instagram' in installed else sorted(installed)[0]
        cls.instagram = cls.env['omni.social.connection'].create({
            'name': 'Brand social page', 'provider': cls.provider, 'purpose_id': cls.team.id})
        social_internal(cls.instagram).write({'connected': True, 'profile_name': '@brand'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s',
                           (cls.env['res.company'].create({'name': 'Elsewhere'}).id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({'name': 'metric.io', 'account_ids': [
            Command.create({'account': f'omni.social.connection,{cls.instagram.id}'}),
            Command.create({'account': f'omni.channel,{cls.channel.id}'})]})
        ig_type = cls.env['omni.channel.type'].search([('code', '=', cls.provider)], limit=1)
        Partner, Contact = cls.env['res.partner'], cls.env['mm.contact']
        cls.aisha_p = Partner.create({'name': 'Aisha Rahman'})
        cls.ben_p = Partner.create({'name': 'Ben Lim'})
        for partner, handle in ((cls.aisha_p, '@aisha.r'), (cls.ben_p, 'benlim')):
            cls.env['omni.partner.channel'].create({'partner_id': partner.id, 'channel_type_id': ig_type.id,
                                                    'handle': handle})
        cls.aisha = Contact.create({'name': 'Aisha Rahman', 'whatsapp': '+60 19 555 0101', 'partner_id': cls.aisha_p.id})
        cls.ben = Contact.create({'name': 'Ben Lim', 'whatsapp': '+60 19 555 0102', 'partner_id': cls.ben_p.id})
        cls.aisha._record_consent('whatsapp', 'opt_in', 'form', 'Website form, offers ticked')

    def setUp(self):
        super().setUp()
        self.adapter = Adapter()
        for target in ('odoo.addons.omni_channel.models.foundation.get_adapter',
                       'odoo.addons.omni_channel.providers.dispatch.get_adapter'):
            patcher = patch(target, return_value=self.adapter)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sender.with_user(self.manager).action_activate(self.channel.generation)
        omni_internal(self.channel).write({'dispatch_enabled': True})

    def _flow(self, **values):
        recipe = self.env.ref('marketing_intel_flow.recipe_comment_whatsapp')
        action = recipe.with_user(self.marketer).with_context(default_brand_id=self.brand.id).action_use()
        flow = self.env['mi.flow'].with_user(self.marketer).browse(action['res_id'])
        flow.step_ids.filtered(lambda s: s.action == 'message').message = 'Hi {first_name}, here is the link.'
        flow.step_ids.filtered(lambda s: s.action == 'todo').unlink()
        if values:
            flow.write(values)
        return flow

    def _approve(self, flow):
        flow.action_request_approval()
        flow.approval_request_id.with_user(self.approver).action_approve()

    _counter = 0

    def _comment(self, author, body):
        TestMarketingFlow._counter += 1
        return social_internal(self.env['omni.social.activity'].sudo()).create({
            'connection_id': self.instagram.id, 'external_key': f'c{self._counter}', 'kind': 'comment',
            'author': author, 'body': body, 'root_key': 'post-1'})

    def _dispatch_all(self):
        Cmd = self.env['omni.command'].sudo()
        while True:
            claim = Cmd._claim_next()
            if claim is None:
                return
            if claim is False:
                continue
            Cmd.browse(claim.command_id)._finish_attempt(claim, dispatch_claim(claim))
            omni_internal(self.channel).write({'next_dispatch_at': False})

    def test_comment_keyword_to_whatsapp_after_one_approval(self):
        old = self._comment('aisha.r', 'INFO before the workflow existed')
        flow = self._flow()
        self.assertEqual(flow.summary, 'When someone comments on a post with “INFO” → send a WhatsApp / Telegram message')
        self._approve(flow)
        self.assertEqual(flow.state, 'active')
        self.assertEqual(flow.approval_request_id.policy_id, self.policy, 'the channel\'s approvers approve messages')
        self.assertEqual(flow.channel_id, self.channel)
        self._comment('aisha.r', 'info please!')
        self._comment('benlim', 'INFO')
        self._comment('stranger_99', 'INFO')
        self._comment('aisha.r', 'INFO again')
        self._comment('dave', 'nice post')
        self._comment('brand', 'INFO sent you a message')  # our own reply
        self.env['mi.flow']._cron_run()
        runs = flow.run_ids
        self.assertNotIn(old.id, [r.source_ref.id for r in runs if r.source_ref], 'only what happens after approval')
        by_person = {r.person: r for r in runs}
        self.assertEqual(set(by_person), {'aisha.r', 'benlim', 'stranger_99'}, 'once per person; keyword only')
        self.assertEqual(by_person['aisha.r'].state, 'done')
        self.assertEqual(by_person['benlim'].state, 'skipped')
        self.assertIn('no opt-in', by_person['benlim'].log)
        self.assertIn('Not a known contact', by_person['stranger_99'].log)
        command = by_person['aisha.r'].command_ids
        self.assertEqual(command.body, 'Hi Aisha, here is the link.')
        self.assertEqual(command.approval_request_id, flow.approval_request_id)
        self._dispatch_all()
        self.assertEqual(command.state, 'accepted', 'the dispatch accepted the workflow approval as evidence')
        self.assertEqual(flow.sent_today, 1)

    def test_daily_limit_changes_and_forged_messages(self):
        flow = self._flow(once_per_person=False)
        self._approve(flow)
        self._comment('aisha.r', 'INFO')
        self._comment('aisha.r', 'INFO 2')
        self.env['mi.flow']._cron_run()
        self.assertEqual(sorted(flow.run_ids.mapped('state')), ['done', 'skipped'])
        self.assertIn('Daily limit', flow.run_ids.filtered(lambda r: r.state == 'skipped').log)
        # Any change pauses the workflow until it is approved again; queued messages lose their evidence.
        command = flow.run_ids.command_ids
        flow.step_ids.message = 'Changed text'
        self.assertEqual(flow.state, 'paused')
        self.assertTrue(flow.changed)
        with self.assertRaises(UserError):
            flow.action_resume()
        self._dispatch_all()
        self.assertNotEqual(command.state, 'accepted')
        # Nobody can forge a workflow message.
        with self.assertRaises(AccessError):
            self.env['omni.command'].with_user(self.marketer).create({
                'channel_id': self.channel.id, 'recipient': '+60195550101', 'body': 'x', 'reason': 'x',
                'mi_flow_run_id': flow.run_ids[0].id})

    def test_cannot_ask_approval_until_ready(self):
        flow = self._flow()
        flow.step_ids.message = False
        with self.assertRaisesRegex(UserError, 'Write the message'):
            flow.action_request_approval()
        flow.step_ids.message = 'Hello'
        flow.action_request_approval()
        flow.approval_request_id.with_user(self.approver).action_refuse()
        self.assertEqual(flow.state, 'draft')
