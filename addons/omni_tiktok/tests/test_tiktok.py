"""TikTok connector against a fake Content Posting API, plus Social wiring."""

import json
from unittest.mock import patch

from odoo.tests import BaseCase, TransactionCase, tagged

from odoo.addons.omni_social.providers import registry
from odoo.addons.omni_social.providers.http import ProviderError
from odoo.addons.omni_tiktok.providers import api

PROFILE = {'id': 'open-1234', 'name': '@acme', 'kind': 'organization'}
VIDEO = {'id': 7, 'kind': 'video', 'mime': 'video/mp4', 'url': ''}
PHOTO = {'id': 1, 'kind': 'image', 'url': 'https://odoo.example/omni/social/media/t/0'}
BUNDLE = {'token': 'tok', 'profile': PROFILE, 'media_bytes': {7: b'\x00' * 2048}}
UPLOAD = 'https://open-upload.tiktokapis.com/upload/?upload_id=1&upload_token=x'


class FakeTikTok:
    def __init__(self, privacy=('PUBLIC_TO_EVERYONE', 'SELF_ONLY'), status='PUBLISH_COMPLETE'):
        self.privacy, self.status, self.posts = list(privacy), status, []

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'open.tiktokapis.com'
        ok = {'error': {'code': 'ok'}}
        if path == '/v2/user/info/':
            return {**ok, 'data': {'user': {'open_id': 'open-1234', 'username': 'acme'}}}, {}
        self.posts.append((path, body))
        if path.endswith('creator_info/query/'):
            return {**ok, 'data': {'privacy_level_options': self.privacy}}, {}
        if path.endswith('video/init/'):
            return {**ok, 'data': {'publish_id': 'v_pub_1', 'upload_url': UPLOAD}}, {}
        if path.endswith('content/init/'):
            return {**ok, 'data': {'publish_id': 'p_pub_1'}}, {}
        if path.endswith('status/fetch/'):
            return {**ok, 'data': {'status': self.status, 'publicaly_available_post_id': [7311]}}, {}
        raise ProviderError('rejected')


def doc(**values):
    base = {'operation': 'post', 'account': 'open-1234', 'body': 'New drop #launch', 'title': 'New drop',
            'format': 'standard', 'media': [VIDEO]}
    base.update(values)
    return base


@tagged('post_install', '-at_install')
class TikTokProtocol(BaseCase):
    def steps(self, graph, payload, put=None, limit=6):
        outcomes, state = [], ''
        with patch.object(api, 'call', graph), patch.object(api, 'put_file', side_effect=put or (lambda *a: None)):
            for _ in range(limit):
                outcome, state, note = api.Adapter().execute(BUNDLE, payload, state)
                outcomes.append(outcome)
                if outcome != 'waiting' or note != 'Preparing media.':
                    break
        return outcomes, state, note

    def test_video_upload_then_status(self):
        uploads = []
        graph = FakeTikTok()
        outcomes, key, note = self.steps(graph, doc(), put=lambda url, raw, mime: uploads.append((url, len(raw))))
        self.assertEqual(outcomes, ['waiting', 'waiting', 'sent'])
        self.assertEqual(uploads, [(UPLOAD, 2048)])
        init = [b for p, b in graph.posts if p.endswith('video/init/')][0]
        self.assertEqual(init['source_info']['video_size'], 2048)
        self.assertEqual(init['post_info'], {'title': 'New drop #launch', 'privacy_level': 'PUBLIC_TO_EVERYONE'})
        self.assertEqual(key, '7311')

    def test_unaudited_apps_post_privately_and_say_so(self):
        graph = FakeTikTok(privacy=('SELF_ONLY',))
        outcomes, _key, note = self.steps(graph, doc())
        self.assertEqual(outcomes[-1], 'sent')
        self.assertIn('visible only to the account owner', note)

    def test_photo_post_pulls_from_the_public_address(self):
        graph = FakeTikTok(status='PROCESSING_DOWNLOAD')
        outcomes, state, note = self.steps(graph, doc(media=[PHOTO, {**PHOTO, 'id': 2}], format='carousel'))
        self.assertEqual(outcomes, ['waiting', 'waiting'])
        self.assertIn('processing', note)
        init = [b for p, b in graph.posts if p.endswith('content/init/')][0]
        self.assertEqual(init['media_type'], 'PHOTO')
        self.assertEqual(init['post_info']['title'], 'New drop')
        self.assertEqual(len(init['source_info']['photo_images']), 2)
        self.assertEqual(json.loads(state)['publish_id'], 'p_pub_1')

    def test_lost_upload_is_uncertain_and_failed_status_is_failure(self):
        outcomes, _s, _n = self.steps(FakeTikTok(), doc(), put=lambda *a: (_ for _ in ()).throw(ProviderError('upload', True)))
        self.assertEqual(outcomes, ['waiting', 'unknown'])
        failing = FakeTikTok(status='FAILED')
        self.assertEqual(self.steps(failing, doc())[0][-1], 'failed')

    def test_validation_and_foreign_upload_hosts(self):
        adapter = api.Adapter()
        for bad in (doc(media=[]), doc(media=[VIDEO, VIDEO]), doc(media=[VIDEO, PHOTO]),
                    doc(media=[PHOTO], title=''), doc(body='x' * 2201), doc(operation='reply')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)
        with self.assertRaises(ValueError):
            api.upload_url('https://evil.example/upload/?x=1')

    def test_read_explains_the_limit(self):
        with patch.object(api, 'call', FakeTikTok()):
            items, note = api.Adapter().read(BUNDLE)
        self.assertEqual(items, [])
        self.assertIn('no API to read comments', note)


@tagged('post_install', '-at_install')
class TikTokInSocial(TransactionCase):
    def test_card_and_sign_in_parameter_name(self):
        card = self.env.ref('omni_channel.channel_type_tiktok')
        self.assertTrue(card.social_ready)
        caps = registry.capabilities('tiktok')
        self.assertEqual(caps.oauth.client_id_param, 'client_key')
        self.assertEqual(caps.operations, ('post',))
