"""X connector against a fake API v2, budget enforcement through Social."""

from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import BaseCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.models.social import internal
from odoo.addons.omni_social.providers import registry
from odoo.addons.omni_social.providers.http import ProviderError
from odoo.addons.omni_x.providers import api

PROFILE = {'id': '4242', 'name': '@acme', 'username': 'acme', 'kind': 'organization'}
BUNDLE = {'token': 'tok', 'profile': PROFILE, 'media_bytes': {1: b'jpeg', 2: b'jpeg'}}
IMAGE = {'id': 1, 'kind': 'image', 'mime': 'image/jpeg', 'url': ''}


class FakeX:
    def __init__(self, post_answer=None):
        self.posts, self.post_answer = [], post_answer

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'api.x.com'
        if path == '/2/users/me':
            return {'data': {'id': '4242', 'username': 'acme'}}, {}
        if method == 'POST':
            self.posts.append((path, body))
            if isinstance(self.post_answer, Exception):
                raise self.post_answer
            return self.post_answer or {'data': {'id': '1790000000000000001'}}, {}
        if path == '/2/users/4242/tweets':
            return {'data': [{'id': '17', 'text': 'Launch', 'created_at': '2026-10-01T10:00:00Z',
                              'public_metrics': {'like_count': 5, 'reply_count': 1}}]}, {}
        if path == '/2/users/4242/mentions':
            return {'data': [{'id': '18', 'text': '@acme nice', 'author_id': '77', 'conversation_id': '17',
                              'created_at': '2026-10-01T11:00:00Z'}],
                    'includes': {'users': [{'id': '77', 'username': 'ann'}]}}, {}
        raise ProviderError('rejected')


def doc(**values):
    base = {'operation': 'post', 'account': '4242', 'body': 'Hello X', 'format': 'standard', 'media': [],
            'target': '', 'root': ''}
    base.update(values)
    return base


@tagged('post_install', '-at_install')
class XProtocol(BaseCase):
    def test_post_reply_and_images(self):
        graph = FakeX()
        with patch.object(api, 'call', graph), patch.object(api, 'upload_image', side_effect=['901', '902']):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc())[:2], ('sent', '1790000000000000001'))
            api.Adapter().execute(BUNDLE, doc(operation='reply', target='18', root='17', body='Thanks!'))
            api.Adapter().execute(BUNDLE, doc(media=[IMAGE, {**IMAGE, 'id': 2}], format='carousel'))
        self.assertEqual(graph.posts[0], ('/2/tweets', {'text': 'Hello X'}))
        self.assertEqual(graph.posts[1][1]['reply'], {'in_reply_to_tweet_id': '18'})
        self.assertEqual(graph.posts[2][1]['media'], {'media_ids': ['901', '902']})

    def test_unreadable_answer_after_posting_is_uncertain(self):
        with patch.object(api, 'call', FakeX(post_answer={'data': {}})):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc())[0], 'unknown')
        with patch.object(api, 'call', FakeX(post_answer=ProviderError('rejected'))):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc())[0], 'failed')

    def test_prices(self):
        adapter = api.Adapter()
        self.assertEqual(adapter.cost('post', doc()), api.POST_PRICE)
        self.assertEqual(adapter.cost('post', doc(body='see https://acme.example')), api.LINK_POST_PRICE)
        self.assertEqual(adapter.cost('post', doc(body='visit acme.com today')), api.LINK_POST_PRICE)
        self.assertAlmostEqual(adapter.read_cost(), 0.10)

    def test_validation(self):
        adapter = api.Adapter()
        for bad in (doc(body='x' * 281), doc(body=''), doc(media=[IMAGE] * 5),
                    doc(operation='reply', target='x', root='1'), doc(operation='message')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)

    def test_read_posts_and_mentions(self):
        with patch.object(api, 'call', FakeX()):
            items, note = api.Adapter().read(BUNDLE)
        self.assertEqual([(i['kind'], i['external_key']) for i in items], [('post', '17'), ('comment', '18')])
        self.assertEqual(items[1]['author'], '@ann')
        self.assertEqual(items[0]['permalink'], 'https://x.com/acme/status/17')
        self.assertIn('charged', note)


@tagged('post_install', '-at_install')
class XBudget(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='x_mgr', groups='omni_channel.group_omni_manager')
        team = cls.env['omni.purpose'].create({'name': 'X QA', 'code': 'x_qa',
                                               'user_ids': [fields.Command.set(cls.manager.ids)]})
        cls.account = cls.env['omni.social.connection'].with_user(cls.manager).create(
            {'name': 'X', 'provider': 'x', 'purpose_id': team.id})
        with patch.object(api.Adapter, 'verify', return_value=PROFILE):
            cls.account.action_connect('synthetic')

    def test_paid_platform_starts_with_the_default_budget(self):
        self.assertTrue(self.env.ref('omni_channel.channel_type_x').social_ready)
        self.assertTrue(self.account.paid_platform)
        self.assertEqual(self.account.monthly_budget, 20.0)
        self.assertIn('of $20.00 this month', self.account.usage_summary)

    def test_link_posts_are_priced_higher_against_the_budget(self):
        self.account.monthly_budget = 0.25
        self.account._check_quota('post', {'body': 'a link https://acme.example'})
        internal(self.env['omni.social.usage']).sudo().create(
            {'connection_id': self.account.id, 'operation': 'post', 'cost': 0.20})
        self.account._check_quota('post', {'body': 'plain text'})
        with self.assertRaisesRegex(UserError, 'monthly budget'):
            self.account._check_quota('post', {'body': 'another https://acme.example'})

    def test_sync_is_charged_and_capped(self):
        with patch.object(api.Adapter, 'read', return_value=([], 'ok')):
            self.account.action_sync()
        usage = self.env['omni.social.usage'].search([('connection_id', '=', self.account.id)])
        self.assertEqual((usage.operation, usage.cost), ('read', 0.10))
        self.account.monthly_budget = 0.15
        with self.assertRaisesRegex(UserError, 'charges for reading'):
            self.account.action_sync()
