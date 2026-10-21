from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry

PERSON = {'id': 'urn:li:person:HOME', 'name': 'Home QA', 'member': 'urn:li:person:HOME', 'kind': 'person'}


@tagged('post_install', '-at_install')
class TestSocialHome(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'linkedin' not in registry.installed(cls.env):
            cls.skipTest(cls, 'Needs omni_linkedin')
        cls.manager = new_test_user(cls.env, login='home_manager', groups='omni_channel.group_omni_manager')
        cls.member = new_test_user(cls.env, login='home_member', groups='omni_channel.group_omni_user')
        cls.outsider = new_test_user(cls.env, login='home_outsider', groups='omni_channel.group_omni_user')
        team = cls.env['omni.purpose'].create({
            'name': 'Home QA', 'code': 'home_qa', 'user_ids': [Command.set([cls.manager.id, cls.member.id])],
        })
        cls.account = cls.env['omni.social.connection'].with_user(cls.manager).create({
            'name': 'Home LinkedIn', 'provider': 'linkedin', 'account_kind': 'person', 'purpose_id': team.id,
        })
        with patch.object(type(registry.provider(cls.env, 'linkedin')), 'verify', return_value=PERSON):
            cls.account.action_connect('synthetic')
        Activity = internal(cls.env['omni.social.activity'])
        cls.comments = Activity.create([{
            'connection_id': cls.account.id, 'external_key': f'urn:li:comment:(urn:li:share:1,{n})',
            'kind': 'comment', 'body': f'Question {n}', 'occurred_at': fields.Datetime.now(),
        } for n in range(3)])
        Activity.create({'connection_id': cls.account.id, 'external_key': 'urn:li:share:1', 'kind': 'post',
                         'body': 'Our post', 'occurred_at': fields.Datetime.now()})

    def _social(self, user):
        items = self.env['ai.home.item'].with_user(user)._live_attention()
        return [i for i in items if i['kind'].startswith('social')]

    def test_team_sees_what_to_answer(self):
        items = self._social(self.member)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], '3 to answer on Home LinkedIn')
        action = items[0]['action']
        self.assertEqual(action['res_model'], 'omni.social.activity')
        found = self.env['omni.social.activity'].with_user(self.member).search(action['domain'])
        self.assertEqual(found, self.comments, 'our own posts are never counted')

    def test_answered_and_others_assignments_drop_out(self):
        self.comments[0].with_user(self.member).action_mark_ignored()
        self.comments[1].with_user(self.manager).action_assign_me()
        self.assertEqual(self._social(self.member)[0]['name'], '1 to answer on Home LinkedIn')
        self.assertEqual(self._social(self.manager)[0]['name'], '2 to answer on Home LinkedIn')

    def test_outsiders_see_nothing(self):
        self.assertEqual(self._social(self.outsider), [])

    def test_failed_posts_of_mine(self):
        post = self.env['omni.social.publication'].with_user(self.member).create({
            'name': 'Broken post', 'connection_id': self.account.id, 'body': 'x', 'reason': 'QA',
        })
        internal(post.sudo()).write({'state': 'failed'})
        names = [i['name'] for i in self._social(self.member)]
        self.assertIn('Broken post', names)
        self.assertNotIn('Broken post', [i['name'] for i in self._social(self.manager)])
