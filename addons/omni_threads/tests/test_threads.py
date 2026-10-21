"""Threads connector against a fake Threads API, plus Social wiring."""

import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import BaseCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.providers import registry
from odoo.addons.omni_social.providers.http import ProviderError
from odoo.addons.omni_threads.providers import api

PROFILE = {'id': '17841', 'name': '@acme', 'username': 'acme', 'kind': 'organization'}
BUNDLE = {'token': 'tok', 'profile': PROFILE}
PHOTO = {'id': 1, 'kind': 'image', 'url': 'https://odoo.example/omni/social/media/t/0'}
VIDEO = {'id': 2, 'kind': 'video', 'url': 'https://odoo.example/omni/social/media/t/1'}


class FakeThreads:
    def __init__(self, routes=None, status='FINISHED'):
        self.routes = {'/v1.0/me': {'id': '17841', 'username': 'acme'}, **(routes or {})}
        self.status = status
        self.posts = []

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'graph.threads.net'
        if method == 'POST':
            self.posts.append((path, body))
            return {'id': str(900 + len(self.posts))}, {}
        if (params or {}).get('fields') == 'id,status':
            return {'id': path.rsplit('/', 1)[-1], 'status': self.status}, {}
        if path not in self.routes:
            raise ProviderError('rejected')
        return self.routes[path], {}


def doc(**values):
    base = {'operation': 'post', 'account': '17841', 'body': 'Hello Threads', 'format': 'standard', 'media': [],
            'target': '', 'root': ''}
    base.update(values)
    return base


@tagged('post_install', '-at_install')
class ThreadsProtocol(BaseCase):
    def run_steps(self, graph, payload, steps=6):
        state, outcomes = '', []
        with patch.object(api, 'call', graph):
            for _step in range(steps):
                outcome, state, note = api.Adapter().execute(BUNDLE, payload, state)
                outcomes.append(outcome)
                if outcome != 'waiting' or note != 'Preparing media.':
                    break
        return outcomes, state

    def test_text_post_is_container_then_publish(self):
        graph = FakeThreads()
        outcomes, key = self.run_steps(graph, doc())
        self.assertEqual(outcomes, ['waiting', 'sent'])
        self.assertEqual(graph.posts[0], ('/v1.0/17841/threads', {'media_type': 'TEXT', 'text': 'Hello Threads'}))
        self.assertEqual(graph.posts[1], ('/v1.0/17841/threads_publish', {'creation_id': '901'}))
        self.assertEqual(key, '902')

    def test_video_waits_for_processing(self):
        graph = FakeThreads(status='IN_PROGRESS')
        outcomes, state = self.run_steps(graph, doc(media=[VIDEO]))
        self.assertEqual(outcomes, ['waiting', 'waiting'])
        self.assertEqual(json.loads(state)['parent'], '901')
        self.assertEqual(len(graph.posts), 1, 'nothing is published while processing')
        graph.status = 'FINISHED'
        with patch.object(api, 'call', graph):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc(media=[VIDEO]), state)[0], 'sent')
        self.assertEqual(graph.posts[0][1]['video_url'], VIDEO['url'])

    def test_already_published_container_is_uncertain(self):
        graph = FakeThreads(status='PUBLISHED')
        with patch.object(api, 'call', graph):
            outcome = api.Adapter().execute(BUNDLE, doc(), json.dumps({'children': [], 'parent': '901'}))[0]
        self.assertEqual(outcome, 'unknown')
        self.assertEqual(graph.posts, [])

    def test_carousel(self):
        graph = FakeThreads()
        media = [PHOTO, {**PHOTO, 'id': 3}, VIDEO]
        outcomes, _state = self.run_steps(graph, doc(format='carousel', media=media))
        self.assertEqual(outcomes, ['waiting'] * 4 + ['sent'])
        self.assertTrue(all(p[1]['is_carousel_item'] for p in graph.posts[:3]))
        self.assertEqual(graph.posts[3][1]['children'], '901,902,903')

    def test_reply_only_under_our_posts(self):
        reply = doc(operation='reply', body='Thanks!', target='555', root='444')
        ours = FakeThreads({'/v1.0/444': {'id': '444', 'username': 'acme'}})
        outcomes, _key = self.run_steps(ours, reply)
        self.assertEqual(outcomes, ['waiting', 'sent'])
        self.assertEqual(ours.posts[0][1]['reply_to_id'], '555')
        theirs = FakeThreads({'/v1.0/444': {'id': '444', 'username': 'someone'}})
        self.assertEqual(self.run_steps(theirs, reply)[0], ['failed'])

    def test_limits(self):
        adapter = api.Adapter()
        for bad in (doc(body='x' * 501), doc(body=''), doc(format='carousel', media=[PHOTO]), doc(operation='message')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)
        caps = registry.capabilities('threads')
        self.assertEqual(caps.daily_limits, {'post': 250, 'reply': 1000})

    def test_read_with_engagement(self):
        graph = FakeThreads({
            '/v1.0/17841/threads': {'data': [{'id': '444', 'text': 'Launch', 'timestamp': '2026-10-01T10:00:00+0000',
                                              'permalink': 'https://www.threads.net/@acme/post/x'},
                                             {'id': '445', 'text': 'my reply', 'is_reply': True}]},
            '/v1.0/444/insights': {'data': [{'name': 'likes', 'values': [{'value': 12}]},
                                            {'name': 'replies', 'values': [{'value': 2}]}]},
            '/v1.0/444/replies': {'data': [{'id': '555', 'text': 'Nice', 'username': 'ann',
                                            'timestamp': '2026-10-01T11:00:00+0000'},
                                           {'id': '556', 'text': 'thanks', 'username': 'acme'}]},
        })
        with patch.object(api, 'call', graph):
            items, _note = api.Adapter().read(BUNDLE)
        self.assertEqual([(i['kind'], i['external_key']) for i in items], [('post', '444'), ('comment', '555')])
        self.assertEqual((items[0]['likes'], items[0]['comments']), (12, 2))
        self.assertEqual(items[1]['author'], '@ann')

    def test_tokens_are_long_lived_and_renewed(self):
        graph = FakeThreads({'/access_token': {'access_token': 'long', 'expires_in': 5184000},
                             '/refresh_access_token': {'access_token': 'renewed', 'expires_in': 5184000}})
        with patch.object(api, 'call', graph):
            token, details = api.Adapter().oauth_token({'access_token': 'short'}, {'client_id': 'a', 'client_secret': 'b'})
            self.assertEqual(token, 'long')
            self.assertIn('expires_at', details)
            self.assertEqual(api.Adapter().oauth_refresh({'token': 'long'})['access_token'], 'renewed')


@tagged('post_install', '-at_install')
class ThreadsInSocial(TransactionCase):
    def test_card_and_renewal_through_social(self):
        card = self.env.ref('omni_channel.channel_type_threads')
        self.assertTrue(card.social_ready)
        self.assertIn('250 posts a day', card.social_rules)
        manager = new_test_user(self.env, login='threads_mgr', groups='omni_channel.group_omni_manager')
        team = self.env['omni.purpose'].create({'name': 'Threads QA', 'code': 'threads_qa',
                                                'user_ids': [fields.Command.set(manager.ids)]})
        account = self.env['omni.social.connection'].with_user(manager).create(
            {'name': 'Threads', 'provider': 'threads', 'purpose_id': team.id})
        past = (fields.Datetime.now() - timedelta(minutes=1)).isoformat()
        with patch.object(api.Adapter, 'verify', return_value=PROFILE):
            account._store_verified('old', '', {'expires_at': past})
        with patch.object(api.Adapter, 'oauth_refresh', return_value={'access_token': 'renewed', 'expires_in': 3600}):
            bundle = account._bundle()
        self.assertEqual(bundle['token'], 'renewed', 'Threads renews without a refresh token')
