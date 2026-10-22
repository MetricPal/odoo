from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.providers import registry
from odoo.addons.social_utm.models.social_utm import public_base

PERSON = {'id': 'urn:li:person:UTM', 'name': 'Person UTM', 'member': 'urn:li:person:UTM', 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialUtm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'linkedin' not in registry.installed(cls.env):
            cls.skipTest(cls, 'Needs omni_linkedin')
        cls.env['ir.config_parameter'].sudo().set_str('web.base.url', 'https://erp.example.org')
        cls.manager = new_test_user(cls.env, login='utm_manager', groups='omni_channel.group_omni_manager')
        cls.operator = new_test_user(cls.env, login='utm_operator', groups='omni_channel.group_omni_user')
        cls.approver = new_test_user(
            cls.env, login='utm_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
        )
        cls.team = cls.env['omni.purpose'].create({
            'name': 'UTM QA', 'code': 'utm_qa',
            'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id, cls.approver.id])],
        })
        policy = cls.env['approval.center.policy'].create({
            'name': 'UTM review', 'company_id': cls.env.company.id,
            'approver_ids': [fields.Command.create({'user_id': cls.approver.id, 'required': True})],
        })
        cls.account = cls.env['omni.social.connection'].with_user(cls.manager).create({
            'name': 'LinkedIn UTM', 'provider': 'linkedin', 'account_kind': 'person',
            'purpose_id': cls.team.id, 'approval_type_id': policy.id, 'public_url': 'https://social.example.org',
        })
        with patch.object(type(registry.provider(cls.env, 'linkedin')), 'verify', return_value=PERSON):
            cls.account.action_connect('synthetic-token')

    def _post(self, body, **values):
        return self.env['omni.social.publication'].with_user(self.operator).create(
            {'name': 'UTM post', 'connection_id': self.account.id, 'body': body, 'reason': 'QA', **values})

    def test_public_base(self):
        self.assertTrue(public_base('https://erp.example.org'))
        for url in ('http://erp.example.org', 'https://localhost:8069', 'https://127.0.0.1', 'https://10.0.0.5',
                    'https://odoo.local', ''):
            self.assertFalse(public_base(url), url)

    def test_campaign_gets_a_tracking_campaign_and_versions_inherit_it(self):
        campaign = self.env['omni.social.campaign'].with_user(self.operator).create({
            'name': 'Autumn launch', 'brief': 'Read more https://metric.io/autumn', 'reason': 'Launch',
            'purpose_id': self.team.id, 'connection_ids': [fields.Command.set(self.account.ids)],
        })
        self.assertEqual(campaign.utm_campaign_id.title, 'Autumn launch')
        campaign.action_create_versions()
        self.assertEqual(campaign.publication_ids.utm_campaign_id, campaign.utm_campaign_id)

    def test_links_become_tracked_before_review(self):
        utm = self.env['utm.campaign'].create({'title': 'Webinar'})
        post = self._post('Join us https://metric.io/webinar?ref=a and https://metric.io/webinar?ref=a.',
                          utm_campaign_id=utm.id)
        self.assertIn('1 link(s) will become tracked short links on erp.example.org', post.link_note)
        post.with_user(self.operator).action_submit()
        self.assertNotIn('https://metric.io/webinar', post.body)
        self.assertEqual(post.body.count('https://erp.example.org/r/'), 2)
        tracker = post._trackers()
        self.assertEqual(len(tracker), 1)
        self.assertEqual(tracker.campaign_id, utm)
        self.assertEqual(tracker.source_id, self.env.ref('utm.utm_source_linkedin'))
        self.assertEqual(tracker.medium_id, self.env.ref('utm.utm_medium_social_media'))
        self.assertEqual(post.payload['links'], [{'short': tracker.short_url, 'url': 'https://metric.io/webinar?ref=a'}])
        request = post.approval_request_id.with_user(self.approver)
        self.assertIn('→ https://metric.io/webinar?ref=a', request.social_links)
        self.assertEqual(post.link_note, '')

    def test_changed_destination_after_review_blocks_publishing(self):
        post = self._post('See https://metric.io/a')
        post.with_user(self.operator).action_submit()
        post.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(post.state, 'approved')
        post._trackers().write({'url': 'https://evil.example/phish'})
        with self.assertRaisesRegex(UserError, 'approved content'):
            post.with_user(self.operator)._frozen()

    def test_links_stay_when_not_public_or_turned_off(self):
        post = self._post('See https://metric.io/b', track_links=False)
        self.assertFalse(post.link_note)
        post.with_user(self.operator)._shorten_links()
        self.assertEqual(post.body, 'See https://metric.io/b')
        self.env['ir.config_parameter'].sudo().set_str('web.base.url', 'http://localhost:8069')
        other = self._post('See https://metric.io/c')
        self.assertIn('Links stay as written', other.link_note)
        other.with_user(self.operator).action_submit()
        self.assertEqual(other.body, 'See https://metric.io/c')
        self.assertFalse(other._trackers())

    def test_platform_sources(self):
        post = self._post('x')
        self.assertEqual(post._utm_source(), self.env.ref('utm.utm_source_linkedin'))
        # Platforms without one of Odoo's sources get one named after the platform, once.
        first = self.env['utm.mixin']._find_or_create_record('utm.source', 'TikTok')
        self.assertEqual(first, self.env['utm.mixin']._find_or_create_record('utm.source', 'tiktok'))

    def test_install_hook_backfills_campaigns(self):
        from odoo.addons.social_utm import _post_init_hook
        campaign = self.env['omni.social.campaign'].with_user(self.operator).create({
            'name': 'Older campaign', 'brief': 'Hello', 'reason': 'Old', 'purpose_id': self.team.id,
            'connection_ids': [fields.Command.set(self.account.ids)],
        })
        campaign.action_create_versions()
        campaign.utm_campaign_id = False
        campaign.publication_ids.utm_campaign_id = False
        _post_init_hook(self.env)
        self.assertEqual(campaign.utm_campaign_id.title, 'Older campaign')
        self.assertEqual(campaign.publication_ids.utm_campaign_id, campaign.utm_campaign_id)
