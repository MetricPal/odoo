"""Facebook Page connector: protocol checks against a fake Graph API, plus Social wiring."""

import json
from unittest.mock import patch

from odoo.tests import BaseCase, TransactionCase, tagged

from odoo.addons.omni_facebook.providers import api
import hashlib
import hmac

from odoo.addons.omni_social.providers import registry, webhook
from odoo.addons.omni_social.providers.http import ProviderError

PAGE = {'id': '1001', 'page': '1001', 'name': 'Acme Page', 'kind': 'organization'}
BUNDLE = {'token': 'page-token', 'profile': PAGE}


class FakeGraph:
    """Answers Graph paths; records every POST."""

    def __init__(self, routes=None):
        self.routes = {'/v25.0/me': {'id': '1001', 'name': 'Acme Page', 'category': 'Software'}, **(routes or {})}
        self.posts = []

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'graph.facebook.com'
        if method == 'POST':
            self.posts.append((path, body))
            answer = self.routes.get(('POST', path), {'id': '1001_%d' % len(self.posts)})
            if isinstance(answer, Exception):
                raise answer
            return answer, {}
        answer = self.routes.get(path)
        if answer is None:
            raise ProviderError('rejected')
        return answer, {}


def doc(**values):
    base = {'operation': 'post', 'account': '1001', 'body': 'Hello Page', 'format': 'standard', 'media': [],
            'target': '', 'root': ''}
    base.update(values)
    return base


PHOTO = {'id': 1, 'kind': 'image', 'url': 'https://odoo.example/omni/social/media/t/0', 'alt_text': 'A'}
VIDEO = {'id': 2, 'kind': 'video', 'url': 'https://odoo.example/omni/social/media/t/1', 'alt_text': ''}


@tagged('post_install', '-at_install')
class FacebookProtocol(BaseCase):
    def run_graph(self, graph, *args):
        with patch.object(api, 'call', graph):
            return api.Adapter().execute(*args)

    def test_verify_accepts_page_tokens_only(self):
        graph = FakeGraph()
        with patch.object(api, 'call', graph):
            self.assertEqual(api.Adapter().verify('t')['name'], 'Acme Page')
            with self.assertRaises(ValueError):
                api.Adapter().verify('t', account='999')
        user_token = FakeGraph({'/v25.0/me': {'id': '55', 'name': 'A person'}})
        with patch.object(api, 'call', user_token), self.assertRaises(ValueError):
            api.Adapter().verify('t')

    def test_text_post(self):
        graph = FakeGraph()
        outcome, key, _note = self.run_graph(graph, BUNDLE, doc())
        self.assertEqual(outcome, 'sent')
        self.assertEqual(graph.posts, [('/v25.0/1001/feed', {'message': 'Hello Page'})])
        self.assertTrue(key.startswith('1001_'))

    def test_photo_and_video_posts(self):
        graph = FakeGraph({('POST', '/v25.0/1001/photos'): {'id': '77', 'post_id': '1001_77'}})
        self.assertEqual(self.run_graph(graph, BUNDLE, doc(media=[PHOTO]))[:2], ('sent', '1001_77'))
        self.assertEqual(graph.posts[0][1], {'url': PHOTO['url'], 'caption': 'Hello Page'})
        graph = FakeGraph({('POST', '/v25.0/1001/videos'): {'id': '88'}})
        self.assertEqual(self.run_graph(graph, BUNDLE, doc(media=[VIDEO]))[:2], ('sent', '88'))
        self.assertEqual(graph.posts[0][1]['file_url'], VIDEO['url'])

    def test_multi_photo_posts_one_mutation_per_step(self):
        media = [PHOTO, {**PHOTO, 'id': 3, 'url': 'https://odoo.example/omni/social/media/t/2'}]
        graph = FakeGraph()
        state = ''
        outcomes = []
        for _step in range(3):
            outcome, state, _note = self.run_graph(graph, BUNDLE, doc(format='carousel', media=media), state)
            outcomes.append(outcome)
            if outcome == 'sent':
                break
        self.assertEqual(outcomes, ['waiting', 'waiting', 'sent'])
        self.assertEqual([p[0] for p in graph.posts], ['/v25.0/1001/photos', '/v25.0/1001/photos', '/v25.0/1001/feed'])
        self.assertFalse(graph.posts[0][1]['published'])
        self.assertEqual(graph.posts[2][1]['attached_media'], [{'media_fbid': '1001_1'}, {'media_fbid': '1001_2'}])

    def test_reply_only_on_this_pages_posts(self):
        self.assertRaises(ValueError, api.node, 'abc')
        reply = doc(operation='reply', body='Thanks!', target='5_9', root='1001_5')
        ours = FakeGraph({'/v25.0/1001_5': {'id': '1001_5', 'from': {'id': '1001'}}})
        self.assertEqual(self.run_graph(ours, BUNDLE, reply)[0], 'sent')
        self.assertEqual(ours.posts, [('/v25.0/5_9/comments', {'message': 'Thanks!'})])
        theirs = FakeGraph({'/v25.0/1001_5': {'id': '1001_5', 'from': {'id': '4242'}}})
        self.assertEqual(self.run_graph(theirs, BUNDLE, reply)[0], 'failed')
        self.assertEqual(theirs.posts, [])

    def test_uncertain_post_is_not_reported_as_failed(self):
        graph = FakeGraph({('POST', '/v25.0/1001/feed'): ProviderError('network', True)})
        self.assertEqual(self.run_graph(graph, BUNDLE, doc())[0], 'unknown')

    def test_validation(self):
        adapter = api.Adapter()
        for bad in (doc(body=''), doc(body='x' * (api.TEXT_LIMIT + 1)), doc(media=[PHOTO, PHOTO]),
                    doc(format='carousel', media=[PHOTO]), doc(format='reel'), doc(operation='message')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)
        adapter.validate(doc(body='', media=[PHOTO]))

    def test_read_skips_our_own_comments(self):
        graph = FakeGraph({
            '/v25.0/1001/posts': {'data': [{'id': '1001_5', 'message': 'Launch', 'created_time': '2026-10-01T10:00:00+0000',
                                            'permalink_url': 'https://www.facebook.com/1001/posts/5',
                                            'reactions': {'summary': {'total_count': 9}},
                                            'comments': {'summary': {'total_count': 2}}}]},
            '/v25.0/1001_5/comments': {'data': [
                {'id': '5_1', 'message': 'Nice', 'from': {'id': '77', 'name': 'Ann'}, 'created_time': '2026-10-01T11:00:00+0000'},
                {'id': '5_2', 'message': 'Thanks Ann', 'from': {'id': '1001', 'name': 'Acme Page'},
                 'created_time': '2026-10-01T12:00:00+0000'},
            ]},
        })
        with patch.object(api, 'call', graph):
            items, note = api.Adapter().read(BUNDLE)
        self.assertEqual([(i['kind'], i['external_key']) for i in items], [('post', '1001_5'), ('comment', '5_1')])
        self.assertEqual(items[0]['likes'], 9)
        self.assertEqual(items[1]['root_key'], '1001_5')
        self.assertIn('20 Page posts', note)

    def test_sign_in_picks_the_page_token(self):
        graph = FakeGraph({'/v25.0/me/accounts': {'data': [{'id': '1001', 'name': 'Acme', 'access_token': 'pt'}]}})
        with patch.object(api, 'call', graph), patch.object(api, 'call_form', return_value={'access_token': 'long'}):
            self.assertEqual(api.Adapter().oauth_token({'access_token': 'short'}, {'client_id': 'a', 'client_secret': 'b'}),
                             ('pt', {}))
        two = FakeGraph({'/v25.0/me/accounts': {'data': [{'id': '1', 'access_token': 'a'}, {'id': '2', 'access_token': 'b'}]}})
        with patch.object(api, 'call', two), patch.object(api, 'call_form', return_value={}):
            with self.assertRaises(ValueError):
                api.Adapter().oauth_token({'access_token': 'short'}, {'client_id': 'a', 'client_secret': 'b'})
            self.assertEqual(api.Adapter().oauth_token({'access_token': 's'}, {'client_id': 'a', 'client_secret': 'b'}, '2'),
                             ('b', {}))


@tagged('post_install', '-at_install')
class FacebookWebhooks(BaseCase):
    def test_meta_signature_challenge_and_page_hints(self):
        raw = json.dumps({'object': 'page', 'entry': [{'id': '1001', 'changes': [{'field': 'feed'}]},
                                                     {'id': '999', 'changes': []}]}).encode()
        good = 'sha256=' + hmac.new(b'app-secret', raw, hashlib.sha256).hexdigest()
        self.assertTrue(webhook.signature('facebook', 'app-secret', raw, good))
        self.assertFalse(webhook.signature('facebook', 'other-secret', raw, good))
        self.assertEqual(webhook.challenge('facebook', 'app-secret', 'verify-me',
                                           {'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me', 'hub.challenge': '42'}),
                         '42')
        with self.assertRaises(ValueError):
            webhook.challenge('facebook', 'app-secret', 'verify-me',
                              {'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '42'})
        self.assertEqual(len(webhook.hints('facebook', PAGE, raw)), 1, 'only this Page\'s entries count')


@tagged('post_install', '-at_install')
class FacebookInSocial(TransactionCase):
    def test_platform_is_ready_in_social(self):
        self.assertIn('facebook', registry.installed(self.env))
        caps = registry.capabilities('facebook')
        self.assertEqual(caps.operations, ('post', 'reply'))
        card = self.env.ref('omni_channel.channel_type_facebook')
        self.assertTrue(card.social_ready)
        self.assertIn('63,206 characters', card.social_rules)
        self.assertIn(('facebook', 'Facebook'), self.env['omni.social.connection']._fields['provider'].selection)
        self.assertTrue(json.dumps(caps.as_dict()))
