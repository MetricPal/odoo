"""Scheduled publishing, the planning board and campaigns."""

from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry


def person(key):
    return {'id': 'urn:li:person:' + key, 'name': key, 'member': 'urn:li:person:' + key, 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialPlanning(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'linkedin' not in registry.installed(cls.env):
            cls.skipTest(cls, 'Needs omni_linkedin')
        cls.manager = new_test_user(cls.env, login='plan_manager', groups='omni_channel.group_omni_manager')
        cls.author = new_test_user(cls.env, login='plan_author', groups='omni_channel.group_omni_user')
        cls.approver = new_test_user(
            cls.env, login='plan_approver',
            groups='omni_channel.group_omni_user,approval_center.group_approval_center_approver',
        )
        cls.team = cls.env['omni.purpose'].create({
            'name': 'Planning QA', 'code': 'planning_qa',
            'user_ids': [fields.Command.set([cls.manager.id, cls.author.id, cls.approver.id])],
        })
        cls.policy = cls.env['approval.center.policy'].create({
            'name': 'Planning review', 'company_id': cls.env.company.id,
            'approver_ids': [fields.Command.create({'user_id': cls.approver.id, 'required': True})],
        })
        cls.LinkedIn = type(registry.provider(cls.env, 'linkedin'))
        cls.accounts = cls.env['omni.social.connection']
        for key in ('PLANA', 'PLANB'):
            account = cls.env['omni.social.connection'].with_user(cls.manager).create({
                'name': 'Account ' + key, 'provider': 'linkedin', 'account_kind': 'person',
                'purpose_id': cls.team.id, 'approval_type_id': cls.policy.id,
            })
            with patch.object(cls.LinkedIn, 'verify', return_value=person(key)):
                account.action_connect('synthetic')
            cls.accounts |= account
        cls.account = cls.accounts[0]

    def _post(self, **values):
        return self.env['omni.social.publication'].with_user(self.author).create({
            'name': 'Planned', 'connection_id': self.account.id, 'body': 'Hello', 'reason': 'QA', **values,
        })

    # ---- scheduling ------------------------------------------------------

    def test_schedule_is_reviewed_and_extends_the_approval(self):
        when = fields.Datetime.now() + timedelta(days=3)
        post = self._post(scheduled_at=when)
        self.assertEqual(post.stage, 'draft')
        post.action_submit()
        self.assertEqual(post.payload['scheduled_at'], fields.Datetime.to_string(when))
        self.assertGreaterEqual(post.expires_at, when + timedelta(hours=2))
        self.assertEqual(post.approval_request_id.social_scheduled_at, when)
        post.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(post.stage, 'scheduled')
        with self.assertRaisesRegex(UserError, 'publishes automatically'):
            post._claim()

    def test_schedule_limits(self):
        with self.assertRaisesRegex(UserError, 'in the future'):
            self._post(scheduled_at=fields.Datetime.now() - timedelta(hours=1))
        far = self._post(scheduled_at=fields.Datetime.now() + timedelta(days=15))
        with self.assertRaisesRegex(UserError, 'at most 14 days'):
            far.action_submit()

    def test_unscheduled_post_keeps_the_review_shape(self):
        post = self._post()
        post.action_submit()
        self.assertNotIn('scheduled_at', post.payload, 'existing reviews compare equal after upgrade')
        self.assertLessEqual(post.expires_at, fields.Datetime.now() + timedelta(hours=24, minutes=1))
        post.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(post.stage, 'ready')

    def test_cron_publishes_due_posts_as_the_requester(self):
        when = fields.Datetime.now() + timedelta(hours=1)
        post = self._post(scheduled_at=when)
        post.action_submit()
        post.approval_request_id.with_user(self.approver).action_approve()
        early = self._post(scheduled_at=fields.Datetime.now() + timedelta(days=2))
        early.action_submit()
        early.approval_request_id.with_user(self.approver).action_approve()
        calls = []

        def publish(records):
            calls.append((records.id, records.env.uid))
            return {}

        Publication = type(self.env['omni.social.publication'])
        with patch.object(Publication, 'action_publish', autospec=True, side_effect=publish):
            self.env['omni.social.publication']._cron_publish_scheduled()
            self.assertEqual(calls, [], 'nothing publishes before its time')
            with freeze_time(when + timedelta(minutes=1)):
                self.env['omni.social.publication']._cron_publish_scheduled()
        self.assertEqual(calls, [(post.id, self.author.id)])

    def test_cron_keeps_the_reason_when_it_cannot_publish(self):
        when = fields.Datetime.now() + timedelta(hours=1)
        post = self._post(scheduled_at=when)
        post.action_submit()
        post.approval_request_id.with_user(self.approver).action_approve()
        Publication = type(self.env['omni.social.publication'])
        with patch.object(Publication, 'action_publish', autospec=True,
                          side_effect=UserError('LinkedIn allows 1 posts per account in 24 hours')), \
                patch.object(self.env.cr, 'commit'), freeze_time(when + timedelta(minutes=1)):
            self.env['omni.social.publication']._cron_publish_scheduled()
        self.assertEqual(post.state, 'approved')
        self.assertIn('Waiting to publish', post.result_note)

    def test_board_and_calendar(self):
        post = self._post()
        self.assertEqual(post.calendar_date, post.create_date)
        groups = self.env['omni.social.publication'].with_user(self.author).with_context(read_group_expand=True).web_read_group(
            [('id', '=', post.id)], ['stage'], ['__count'],
        )['groups']
        stages = [g['stage'][0] if isinstance(g['stage'], (list, tuple)) else g['stage'] for g in groups]
        self.assertEqual(stages[:6], ['draft', 'review', 'scheduled', 'ready', 'published', 'attention'])
        internal(post).write({'state': 'sent', 'published_at': fields.Datetime.now() + timedelta(minutes=5)})
        self.assertEqual(post.stage, 'published')
        self.assertEqual(post.calendar_date, post.published_at)

    def test_too_long_text_is_flagged_before_submit(self):
        post = self._post(body='x' * 3005)
        self.assertIn('3005 of 3000', post.limit_note)

    # ---- campaigns -------------------------------------------------------

    def _campaign(self, **values):
        return self.env['omni.social.campaign'].with_user(self.author).create({
            'name': 'Launch', 'brief': 'We launched!', 'reason': 'Product launch',
            'purpose_id': self.team.id, 'connection_ids': [fields.Command.set(self.accounts.ids)], **values,
        })

    def test_campaign_from_brief_to_approved(self):
        campaign = self._campaign()
        self.assertEqual(campaign.state, 'draft')
        self.assertTrue(campaign.missing_versions)
        campaign.action_create_versions()
        self.assertFalse(campaign.missing_versions)
        campaign.action_create_versions()  # idempotent
        self.assertEqual(campaign.version_count, 2)
        self.assertEqual(set(campaign.publication_ids.connection_id.ids), set(self.accounts.ids))
        self.assertTrue(all(v.body == 'We launched!' for v in campaign.publication_ids))
        self.assertFalse(campaign.with_user(self.approver).can_approve)
        campaign.action_submit_all()
        self.assertEqual(campaign.state, 'review')
        self.assertEqual(len(campaign.publication_ids.approval_request_id), 2, 'each version keeps its own review')
        self.assertFalse(campaign.can_approve, 'the author cannot approve')
        reviewer = campaign.with_user(self.approver)
        self.assertTrue(reviewer.can_approve)
        reviewer.action_approve_all()
        self.assertEqual(campaign.state, 'approved')
        self.assertEqual(set(campaign.publication_ids.mapped('state')), {'approved'})
        with self.assertRaisesRegex(UserError, 'Nothing here'):
            reviewer.action_approve_all()

    def test_campaign_submit_names_the_failing_account(self):
        campaign = self._campaign(brief='x' * 3005)
        campaign.action_create_versions()
        with self.assertRaisesRegex(UserError, 'Account PLANA'):
            campaign.action_submit_all()

    def test_campaign_belongs_to_its_author(self):
        campaign = self._campaign()
        with self.assertRaises(AccessError):
            campaign.with_user(self.approver).write({'brief': 'Changed'})

    def test_campaign_publishes_unscheduled_versions_only(self):
        campaign = self._campaign()
        campaign.action_create_versions()
        campaign.action_submit_all()
        campaign.with_user(self.approver).action_approve_all()
        later = campaign.publication_ids[1]
        internal(later).write({'scheduled_at': fields.Datetime.now() + timedelta(days=1)})
        calls = []
        Publication = type(self.env['omni.social.publication'])
        with patch.object(Publication, 'action_publish', autospec=True, side_effect=lambda r: calls.append(r.id)):
            campaign.action_publish_ready()
        self.assertEqual(calls, [campaign.publication_ids[0].id])
