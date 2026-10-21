"""Inbox handling of imported activity and the weekly report."""

from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry

PERSON = {'id': 'urn:li:person:INBOX', 'name': 'Inbox QA', 'member': 'urn:li:person:INBOX', 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialInbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'linkedin' not in registry.installed(cls.env):
            cls.skipTest(cls, 'Needs omni_linkedin')
        cls.manager = new_test_user(cls.env, login='inbox_manager', groups='omni_channel.group_omni_manager')
        cls.member = new_test_user(cls.env, login='inbox_member', groups='omni_channel.group_omni_user')
        cls.outsider = new_test_user(cls.env, login='inbox_outsider', groups='omni_channel.group_omni_user')
        team = cls.env['omni.purpose'].create({
            'name': 'Inbox QA', 'code': 'inbox_qa', 'user_ids': [Command.set([cls.manager.id, cls.member.id])],
        })
        cls.account = cls.env['omni.social.connection'].with_user(cls.manager).create({
            'name': 'Inbox LinkedIn', 'provider': 'linkedin', 'account_kind': 'person', 'purpose_id': team.id,
        })
        with patch.object(type(registry.provider(cls.env, 'linkedin')), 'verify', return_value=PERSON):
            cls.account.action_connect('synthetic')
        Activity = internal(cls.env['omni.social.activity'])
        cls.post = Activity.create({'connection_id': cls.account.id, 'external_key': 'urn:li:share:1', 'kind': 'post',
                                    'body': 'Our post', 'likes': 7, 'comments': 2, 'occurred_at': fields.Datetime.now()})
        cls.comment = Activity.create({'connection_id': cls.account.id, 'external_key': 'urn:li:comment:(urn:li:share:1,5)',
                                       'kind': 'comment', 'body': 'Nice!', 'author': 'Ann',
                                       'occurred_at': fields.Datetime.now()})

    def test_new_comments_wait_and_our_posts_do_not(self):
        self.assertEqual(self.comment.inbox_state, 'new')
        self.assertEqual(self.post.inbox_state, 'ignored')

    def test_team_members_handle_activity(self):
        comment = self.comment.with_user(self.member)
        comment.action_assign_me()
        self.assertEqual(comment.assignee_id, self.member)
        comment.action_mark_ignored()
        self.assertEqual(comment.inbox_state, 'ignored')
        comment.action_mark_new()
        self.assertEqual(comment.inbox_state, 'new')
        with self.assertRaises(AccessError):
            comment.write({'body': 'Edited'})

    def test_outsiders_cannot_handle_activity(self):
        with self.assertRaises(AccessError):
            self.comment.with_user(self.outsider).action_mark_ignored()

    def test_published_reply_marks_the_comment_replied(self):
        reply = self.env['omni.social.publication'].with_user(self.member).create({
            'name': 'Reply', 'connection_id': self.account.id, 'operation': 'reply', 'target_id': self.comment.id,
            'body': 'Thanks!', 'reason': 'QA',
        })
        reply._social_sent()
        self.assertEqual(self.comment.inbox_state, 'replied')

    def test_resync_keeps_the_handling_state(self):
        self.comment.with_user(self.member).action_mark_ignored()
        fixture = {'external_key': self.comment.external_key, 'kind': 'comment', 'body': 'Nice!', 'author': 'Ann',
                   'occurred_at': fields.Datetime.now()}
        with patch.object(type(registry.provider(self.env, 'linkedin')), 'read', return_value=([fixture], 'ok')):
            self.account.action_sync()
        self.assertEqual(self.comment.inbox_state, 'ignored')

    def test_weekly_report(self):
        post = self.env['omni.social.publication'].with_user(self.member).create({
            'name': 'Published', 'connection_id': self.account.id, 'body': 'Hi', 'reason': 'QA',
        })
        internal(post.sudo()).write({'state': 'sent', 'published_at': fields.Datetime.now()})
        self.env.flush_all()
        rows = self.env['omni.social.report'].with_user(self.member).search([('connection_id', '=', self.account.id)])
        self.assertEqual(sum(rows.mapped('published')), 1)
        self.assertEqual(sum(rows.mapped('likes')), 7)
        self.assertEqual(sum(rows.mapped('comments')), 2)
        self.assertEqual(sum(rows.mapped('received')), 1)
        self.assertFalse(self.env['omni.social.report'].with_user(self.outsider).search(
            [('connection_id', '=', self.account.id)]))
