from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestClientPortal(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        groups = 'marketing_intel.group_mi_user'
        if cls.env.ref('mass_mailing.group_mass_mailing_user', raise_if_not_found=False):
            groups += ',mass_mailing.group_mass_mailing_user'
        cls.marketer = new_test_user(cls.env, 'mipo_marketer', groups=groups)
        cls.client_user = new_test_user(cls.env, 'mipo_client', groups='base.group_portal', password='mipo_client1')
        cls.other_client = new_test_user(cls.env, 'mipo_other', groups='base.group_portal', password='mipo_other1')
        elsewhere = cls.env['res.company'].create({'name': 'Elsewhere'})
        cls.env.cr.execute('UPDATE mi_brand SET company_id = %s WHERE company_id = %s', (elsewhere.id, cls.env.company.id))
        cls.env.invalidate_all()
        cls.brand = cls.env['mi.brand'].sudo().create({
            'name': 'Klinik Sihat', 'owner_type': 'client', 'partner_id': cls.client_user.partner_id.id,
            'portal_partner_ids': [Command.set(cls.client_user.partner_id.ids)], 'client_signoff': True,
            'client_proofs': True, 'member_ids': [Command.set(cls.marketer.ids)]})
        email = cls.env['mi.channel'].search([('code', '=', 'email')])
        start = date.today() + timedelta(days=7)
        cls.plan = cls.env['mi.plan'].with_user(cls.marketer).create({
            'name': 'Health screening month', 'brand_id': cls.brand.id, 'date_start': start,
            'date_end': start + timedelta(days=20), 'channel_ids': [Command.set(email.ids)],
            'message': 'Free screening in March.'})

    def test_signoff_is_required_before_review_and_reset_on_refusal(self):
        plan = self.plan.with_user(self.marketer)
        result = plan.action_submit_review()
        self.assertIn('Ask the client', result['params']['message'])
        plan.action_ask_client()
        self.assertEqual(plan.client_state, 'waiting')
        with self.assertRaises(AccessError):
            plan.sudo()._client_decide(self.other_client.partner_id, True)
        with self.assertRaises(UserError):
            plan.sudo()._client_decide(self.client_user.partner_id, False, '')
        plan.sudo()._client_decide(self.client_user.partner_id, False, 'Use the new logo')
        self.assertEqual(plan.client_state, 'changes')
        self.assertIn('Use the new logo', plan.action_submit_review()['params']['message'])
        plan.action_ask_client()
        plan.sudo()._client_decide(self.client_user.partner_id, True)
        self.assertEqual(plan.client_state, 'approved')
        self.assertFalse(plan._review_blockers())

    def test_portal_pages_show_only_the_clients_brands(self):
        self.plan.with_user(self.marketer).action_ask_client()
        self.authenticate('mipo_client', 'mipo_client1')
        page = self.url_open('/my/marketing/brand/%s' % self.brand.id)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Health screening month', page.text)
        self.assertIn('Sign off the campaign', page.text)
        page = self.url_open('/my/marketing/campaign/%s' % self.plan.id)
        self.assertIn('Free screening in March.', page.text)
        self.assertIn('Approve the campaign', page.text)
        self.assertNotIn('Budget', page.text)
        # the decision form works through the portal
        page = self.url_open('/my/marketing/campaign/%s/decision' % self.plan.id,
                             data={'decision': 'approve', 'feedback': 'Looks good', 'csrf_token': self.csrf_token()})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(self.plan.client_state, 'approved')
        # requests from the portal
        page = self.url_open('/my/marketing/brand/%s/request' % self.brand.id,
                             data={'name': 'Raya promo', 'goal': '100 bookings', 'details': 'Before Raya.',
                                   'csrf_token': self.csrf_token()})
        self.assertEqual(page.status_code, 200)
        request = self.env['mi.request'].search([('name', '=', 'Raya promo')])
        self.assertTrue(request.from_portal)
        self.assertEqual(request.requested_by, self.client_user.partner_id)
        self.assertIn('Before Raya', request.description)
        # someone else's client sees nothing
        self.authenticate('mipo_other', 'mipo_other1')
        self.assertEqual(self.url_open('/my/marketing/brand/%s' % self.brand.id).status_code, 404)
        self.assertEqual(self.url_open('/my/marketing/campaign/%s' % self.plan.id).status_code, 404)

    def test_client_reviews_proofs_in_the_portal(self):
        proof = self.env['mi.proof'].with_user(self.marketer).with_context(default_plan_id=self.plan.id).create({
            'name': 'Screening poster', 'plan_id': self.plan.id, 'item_id': self.plan.item_ids.id,
            'body': 'Free screening all March.'})
        self.assertTrue(proof.client_review)
        proof.action_send()
        self.authenticate('mipo_client', 'mipo_client1')
        page = self.url_open('/my/marketing/proof/%s' % proof.id)
        self.assertIn('Free screening all March.', page.text)
        self.url_open('/my/marketing/proof/%s/decision' % proof.id,
                      data={'decision': 'changes', 'feedback': 'Add the address', 'csrf_token': self.csrf_token()})
        self.assertEqual(proof.state, 'changes')
        self.assertEqual(proof.feedback, 'Add the address')
        proof.with_user(self.marketer).write({'body': 'Free screening all March at Jalan Ampang.'})
        proof.with_user(self.marketer).action_send()
        proof.sudo()._client_decide(self.client_user.partner_id, True)
        self.assertEqual(proof.state, 'approved')
        self.assertEqual(self.plan.item_ids.content_text, 'Free screening all March at Jalan Ampang.')
