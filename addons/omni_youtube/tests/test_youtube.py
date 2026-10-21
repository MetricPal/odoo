"""YouTube connector against a fake Data API, plus Social wiring."""

import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import BaseCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_social.providers import registry
from odoo.addons.omni_social.providers.http import ProviderError
from odoo.addons.omni_youtube.providers import api

CHANNEL = 'UC' + 'a' * 22
PROFILE = {'id': CHANNEL, 'name': 'Acme TV', 'kind': 'organization'}
VIDEO = {'id': 7, 'kind': 'video', 'mime': 'video/mp4', 'url': ''}
BUNDLE = {'token': 'tok', 'profile': PROFILE, 'media_bytes': {7: b'\x00' * 1024}}
SESSION = 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=XYZ'


class FakeYouTube:
    def __init__(self, routes=None):
        self.routes = {'/youtube/v3/channels': {'items': [{'id': CHANNEL, 'snippet': {'title': 'Acme TV'}}]},
                       **(routes or {})}
        self.posts = []

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'www.googleapis.com'
        if method == 'POST':
            self.posts.append((path, params, body, headers))
            if path == '/upload/youtube/v3/videos':
                return {}, {'Location': SESSION}
            return {'id': 'Ugx' + 'c' * 10}, {}
        key = path if path != '/youtube/v3/channels' or (params or {}).get('mine') else path + '#id'
        answer = self.routes.get(key, self.routes.get(path))
        if answer is None:
            raise ProviderError('rejected')
        return answer, {}


def doc(**values):
    base = {'operation': 'post', 'account': CHANNEL, 'body': 'All about our launch', 'title': 'Launch video',
            'format': 'standard', 'media': [VIDEO], 'target': '', 'root': ''}
    base.update(values)
    return base


@tagged('post_install', '-at_install')
class YouTubeProtocol(BaseCase):
    def test_upload_opens_a_session_then_sends_bytes_once(self):
        graph = FakeYouTube()
        sent = []

        def put(url, token, raw, mime):
            sent.append((url, len(raw), mime))
            return {'id': 'dQw4w9WgXcQ', 'status': {'privacyStatus': 'private'}}

        with patch.object(api, 'call', graph), patch.object(api, 'put_video', side_effect=put):
            outcome, container, note = api.Adapter().execute(BUNDLE, doc())
            self.assertEqual((outcome, container, note), ('waiting', SESSION, 'Preparing media.'))
            path, params, body, headers = graph.posts[0]
            self.assertEqual(params['uploadType'], 'resumable')
            self.assertEqual(body['snippet'], {'title': 'Launch video', 'description': 'All about our launch'})
            self.assertEqual(headers['X-Upload-Content-Length'], '1024')
            self.assertEqual(sent, [])
            outcome, key, note = api.Adapter().execute(BUNDLE, doc(), container)
        self.assertEqual((outcome, key), ('sent', 'dQw4w9WgXcQ'))
        self.assertIn('kept it private', note)
        self.assertEqual(sent, [(SESSION, 1024, 'video/mp4')])

    def test_interrupted_byte_upload_is_uncertain(self):
        with patch.object(api, 'call', FakeYouTube()), \
                patch.object(api, 'put_video', side_effect=ProviderError('upload', True)):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc(), SESSION)[0], 'unknown')

    def test_session_url_must_be_googles(self):
        for bad in ('https://evil.example/upload/youtube/v3/videos?upload_id=1',
                    'http://www.googleapis.com/upload/youtube/v3/videos?upload_id=1',
                    'https://www.googleapis.com/upload/other?upload_id=1',
                    'https://www.googleapis.com/upload/youtube/v3/videos'):
            with self.assertRaises(ValueError):
                api.session_url(bad)
        with patch.object(api, 'call', FakeYouTube()):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc(), 'https://evil.example/x')[0], 'failed')

    def test_validation(self):
        adapter = api.Adapter()
        for bad in (doc(media=[]), doc(title=''), doc(title='x' * 101), doc(body='<script>'),
                    doc(media=[{**VIDEO, 'kind': 'image'}]), doc(operation='message')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)

    def test_replies_on_our_videos_only(self):
        ours = FakeYouTube({'/youtube/v3/videos': {'items': [{'id': 'dQw4w9WgXcQ', 'snippet': {'channelId': CHANNEL}}]}})
        reply = doc(operation='reply', body='Thanks!', root='dQw4w9WgXcQ', target='UgxCOMMENT1', media=[])
        with patch.object(api, 'call', ours):
            self.assertEqual(api.Adapter().execute(BUNDLE, reply)[0], 'sent')
            self.assertEqual(ours.posts[-1][0], '/youtube/v3/comments')
            self.assertEqual(ours.posts[-1][2]['snippet']['parentId'], 'UgxCOMMENT1')
            on_video = doc(operation='reply', body='Hello all', root='dQw4w9WgXcQ', target='dQw4w9WgXcQ', media=[])
            self.assertEqual(api.Adapter().execute(BUNDLE, on_video)[0], 'sent')
            self.assertEqual(ours.posts[-1][0], '/youtube/v3/commentThreads')
        theirs = FakeYouTube({'/youtube/v3/videos': {'items': [{'id': 'dQw4w9WgXcQ', 'snippet': {'channelId': 'UC' + 'b' * 22}}]}})
        with patch.object(api, 'call', theirs):
            self.assertEqual(api.Adapter().execute(BUNDLE, reply)[0], 'failed')
            self.assertEqual(theirs.posts, [])

    def test_read_uploads_and_comments(self):
        graph = FakeYouTube({
            '/youtube/v3/channels#id': {'items': [{'contentDetails': {'relatedPlaylists': {'uploads': 'UUa'}}}]},
            '/youtube/v3/playlistItems': {'items': [{'snippet': {'title': 'Launch', 'description': 'Our launch'},
                                                     'contentDetails': {'videoId': 'dQw4w9WgXcQ',
                                                                        'videoPublishedAt': '2026-10-01T10:00:00Z'}}]},
            '/youtube/v3/videos': {'items': [{'id': 'dQw4w9WgXcQ', 'statistics': {'likeCount': '40', 'commentCount': '2'}}]},
            '/youtube/v3/commentThreads': {'items': [
                {'snippet': {'topLevelComment': {'id': 'UgxCOMMENT1', 'snippet': {
                    'textOriginal': 'Great video', 'authorDisplayName': 'Ann', 'publishedAt': '2026-10-01T11:00:00Z',
                    'authorChannelId': {'value': 'UC' + 'z' * 22}}}}},
                {'snippet': {'topLevelComment': {'id': 'UgxCOMMENT2', 'snippet': {
                    'textOriginal': 'Thanks', 'authorChannelId': {'value': CHANNEL}}}}},
            ]},
        })
        with patch.object(api, 'call', graph):
            result, _note = api.Adapter().read(BUNDLE)
        self.assertEqual([(i['kind'], i['external_key']) for i in result],
                         [('post', 'dQw4w9WgXcQ'), ('comment', 'UgxCOMMENT1')])
        self.assertEqual(result[0]['likes'], 40)
        self.assertEqual(result[0]['permalink'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')


@tagged('post_install', '-at_install')
class YouTubeInSocial(TransactionCase):
    def test_subject_becomes_the_reviewed_title(self):
        card = self.env.ref('omni_channel.channel_type_youtube')
        self.assertTrue(card.social_ready)
        caps = registry.capabilities('youtube')
        self.assertTrue(caps.upload_bytes and caps.media_required)
        self.assertEqual(dict(caps.oauth.extra)['access_type'], 'offline')
        manager = new_test_user(self.env, login='yt_mgr', groups='omni_channel.group_omni_manager')
        team = self.env['omni.purpose'].create({'name': 'YouTube QA', 'code': 'yt_qa',
                                                'user_ids': [fields.Command.set(manager.ids)]})
        account = self.env['omni.social.connection'].with_user(manager).create(
            {'name': 'YouTube', 'provider': 'youtube', 'purpose_id': team.id})
        with patch.object(api.Adapter, 'verify', return_value=PROFILE):
            account.action_connect('synthetic')
        post = self.env['omni.social.publication'].with_user(manager).create(
            {'name': 'Our launch', 'connection_id': account.id, 'body': 'Description', 'reason': 'QA'})
        with patch.object(api.Adapter, 'validate'), \
                patch.object(type(post), '_check_capabilities'):
            self.assertEqual(post._document('t')['title'], 'Our launch')
        self.assertTrue(json.dumps(caps.as_dict()))
