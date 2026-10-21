"""No-traffic media staging and signature regressions."""

import hashlib
import hmac
import json
from unittest.mock import Mock, patch
from odoo.tests import BaseCase, tagged

from odoo.addons.omni_social.providers import webhook
from .test_protocol import ig, li, http, PROFILE, IG

MEDIA = [
    {'id': 1, 'kind': 'image', 'url': 'https://public.example/1', 'digest': 'a', 'alt_text': 'First'},
    {'id': 2, 'kind': 'image', 'url': 'https://public.example/2', 'digest': 'b', 'alt_text': 'Second'},
]


def doc(provider='instagram', fmt='carousel', media=None):
    return {
        'operation': 'post',
        'account': '100' if provider == 'instagram' else PROFILE['id'],
        'body': 'Exact caption',
        'format': fmt,
        'media': MEDIA if media is None else media,
    }


@tagged('post_install', '-at_install')
class MediaProtocol(BaseCase):
    def test_instagram_carousel_stages_order_and_one_mutation_each(self):
        adapter = ig.Adapter()
        payload = doc()
        state = ''
        bundle = {'token': 'synthetic', 'profile': IG}
        with (
            patch.object(adapter, 'verify', return_value=IG),
            patch.object(ig, 'get', return_value={'status_code': 'FINISHED'}),
            patch.object(ig, 'post', side_effect=[{'id': '11'}, {'id': '12'}, {'id': '13'}, {'id': '14'}]) as send,
        ):
            for count in range(4):
                outcome, state, note = adapter.execute(bundle, payload, state)
                self.assertEqual(send.call_count, count + 1)
            self.assertEqual(outcome, 'sent')
            self.assertEqual(state, '14')
            bodies = [c.args[3] for c in send.call_args_list]
            self.assertEqual(bodies[0], {'image_url': MEDIA[0]['url'], 'is_carousel_item': True})
            self.assertEqual(bodies[1]['image_url'], MEDIA[1]['url'])
            self.assertEqual(bodies[2], {'media_type': 'CAROUSEL', 'caption': 'Exact caption', 'children': '11,12'})
            self.assertEqual(bodies[3], {'creation_id': '13'})

    def test_instagram_processing_reuses_children_without_post(self):
        state = json.dumps({'children': ['11', '12'], 'parent': ''})
        adapter = ig.Adapter()
        with (
            patch.object(adapter, 'verify', return_value=IG),
            patch.object(ig, 'get', return_value={'status_code': 'IN_PROGRESS'}),
            patch.object(ig, 'post') as send,
        ):
            outcome, key, note = adapter.execute({'token': 't', 'profile': IG}, doc(), state)
            self.assertEqual(outcome, 'waiting')
            self.assertEqual(json.loads(key)['children'], ['11', '12'])
            send.assert_not_called()

    def test_instagram_unknown_create_no_retry_result(self):
        adapter = ig.Adapter()
        with (
            patch.object(adapter, 'verify', return_value=IG),
            patch.object(ig, 'post', side_effect=http.ProviderError('timeout', True)),
        ):
            self.assertEqual(adapter.execute({'token': 't', 'profile': IG}, doc())[0], 'unknown')

    def test_reel_and_business_story_payloads(self):
        for fmt, kind, expected in [
            (
                'reel',
                'video',
                {
                    'video_url': 'https://public.example/v',
                    'media_type': 'REELS',
                    'share_to_feed': True,
                    'caption': 'Exact caption',
                },
            ),
            ('story', 'image', {'image_url': 'https://public.example/v', 'media_type': 'STORIES'}),
            ('story', 'video', {'video_url': 'https://public.example/v', 'media_type': 'STORIES'}),
        ]:
            adapter = ig.Adapter()
            profile = {**IG, 'account_type': 'BUSINESS'}
            payload = doc(fmt=fmt, media=[{**MEDIA[0], 'kind': kind, 'url': 'https://public.example/v'}])
            if fmt == 'story':
                payload['body'] = ''
            with (
                patch.object(adapter, 'verify', return_value=profile),
                patch.object(ig, 'post', return_value={'id': '1'}) as send,
            ):
                self.assertEqual(adapter.execute({'token': 't', 'profile': profile}, payload)[0], 'waiting')
                self.assertEqual(send.call_args.args[3], expected)

    def test_creator_cannot_publish_story(self):
        adapter = ig.Adapter()
        payload = doc(fmt='story', media=MEDIA[:1])
        payload['body'] = ''
        with (
            patch.object(adapter, 'verify', return_value={**IG, 'account_type': 'MEDIA_CREATOR'}),
            patch.object(ig, 'post') as send,
        ):
            self.assertEqual(adapter.execute({'token': 't', 'profile': IG}, payload)[0], 'failed')
            send.assert_not_called()

    def test_mixed_carousel_video_child_has_no_caption(self):
        adapter = ig.Adapter()
        payload = doc(media=[{**MEDIA[0], 'kind': 'video'}, MEDIA[1]])
        with (
            patch.object(adapter, 'verify', return_value=IG),
            patch.object(ig, 'post', return_value={'id': '1'}) as send,
        ):
            adapter.execute({'token': 't', 'profile': IG}, payload)
            self.assertEqual(
                send.call_args.args[3], {'video_url': MEDIA[0]['url'], 'is_carousel_item': True, 'media_type': 'VIDEO'}
            )

    def test_instagram_active_stories_imported_separately(self):
        adapter = ig.Adapter()

        def edges(token, identity, edge, **params):
            if edge == 'stories':
                return {'data': [{'id': '42', 'media_type': 'IMAGE', 'timestamp': '2026-01-01T12:00:00Z'}]}
            return {'data': []}

        with patch.object(adapter, 'verify', return_value=IG), patch.object(ig, 'edge', side_effect=edges):
            items, note = adapter.read({'token': 't', 'profile': IG})
            self.assertEqual(items[0]['format'], 'STORY')
            self.assertEqual(items[0]['external_key'], '42')

    def test_format_and_count_limits(self):
        for payload in [
            doc(media=MEDIA[:1]),
            doc(media=MEDIA * 6),
            doc(fmt='reel', media=MEDIA[:1]),
            doc(fmt='story', media=MEDIA[:1]),
        ]:
            with self.assertRaises(ValueError):
                ig.Adapter().validate(payload)
        with self.assertRaises(ValueError):
            li.Adapter().validate(doc('linkedin', 'reel', MEDIA[:1]))
        with self.assertRaises(ValueError):
            li.Adapter().validate(doc('linkedin', media=MEDIA * 11))

    def test_linkedin_initialize_upload_then_owned_ordered_publish(self):
        adapter = li.Adapter()
        payload = doc('linkedin')
        bundle = {'token': 'synthetic', 'profile': PROFILE, 'media_bytes': {1: b'jpeg1', 2: b'jpeg2'}}
        state = ''
        initial = [
            ({'value': {'image': 'urn:li:image:A', 'uploadUrl': 'https://www.linkedin.com/dms-uploads/a'}}, {}),
            ({'value': {'image': 'urn:li:image:B', 'uploadUrl': 'https://www.linkedin.com/dms-uploads/b'}}, {}),
        ]
        with (
            patch.object(adapter, 'verify', return_value=PROFILE),
            patch.object(li, 'call', side_effect=initial) as init,
            patch.object(li, 'upload_linkedin') as upload,
            patch.object(
                li,
                'get',
                side_effect=[
                    {'id': 'urn:li:image:A', 'owner': PROFILE['id'], 'status': 'AVAILABLE'},
                    {'id': 'urn:li:image:B', 'owner': PROFILE['id'], 'status': 'AVAILABLE'},
                ],
            ),
            patch.object(li, 'request', return_value=({}, {'x-restli-id': 'urn:li:ugcPost:99'})) as publish,
        ):
            for count in range(5):
                outcome, state, note = adapter.execute(bundle, payload, state)
            self.assertEqual(outcome, 'sent')
            self.assertEqual(init.call_count, 2)
            self.assertEqual(upload.call_count, 2)
            self.assertEqual(publish.call_count, 1)
            self.assertEqual([c.args[2] for c in upload.call_args_list], [b'jpeg1', b'jpeg2'])
            self.assertEqual(
                publish.call_args.args[2]['content'],
                {
                    'multiImage': {
                        'images': [
                            {'id': 'urn:li:image:A', 'altText': 'First'},
                            {'id': 'urn:li:image:B', 'altText': 'Second'},
                        ]
                    }
                },
            )

    def test_linkedin_wrong_image_owner_blocks_post(self):
        adapter = li.Adapter()
        state = json.dumps(
            {'images': [{'id': 'urn:li:image:A', 'url': 'https://www.linkedin.com/dms-uploads/a', 'uploaded': True}]}
        )
        with (
            patch.object(adapter, 'verify', return_value=PROFILE),
            patch.object(
                li, 'get', return_value={'id': 'urn:li:image:A', 'owner': 'urn:li:person:OTHER', 'status': 'AVAILABLE'}
            ),
            patch.object(li, 'request') as send,
        ):
            self.assertEqual(
                adapter.execute({'token': 't', 'profile': PROFILE}, doc('linkedin', 'standard', MEDIA[:1]), state)[0],
                'failed',
            )
            send.assert_not_called()

    def test_linkedin_upload_hosts_and_redirects(self):
        for url in [
            'http://www.linkedin.com/dms-uploads/a',
            'https://evil.example/dms-uploads/a',
            'https://www.linkedin.com.evil.example/dms-uploads/a',
            'https://www.linkedin.com/other',
            'https://user@www.linkedin.com/dms-uploads/a',
        ]:
            with self.assertRaises(ValueError):
                http.upload_linkedin(url, 'token', b'jpeg')
        response = Mock(status_code=302)
        session = Mock()
        session.request.return_value = response
        with (
            patch.object(http.requests, 'Session', return_value=session),
            self.assertRaises(http.ProviderError) as error,
        ):
            http.upload_linkedin('https://www.linkedin.com/dms-uploads/a', 'token', b'jpeg')
        self.assertTrue(error.exception.uncertain)
        self.assertFalse(session.trust_env)
        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])


@tagged('post_install', '-at_install')
class WebhookProtocol(BaseCase):
    def test_exact_raw_signatures_both_platforms(self):
        raw = b'{"entry": []}'
        for platform in ['instagram', 'linkedin']:
            msg = raw if platform == 'instagram' else b'hmacsha256=' + raw
            header = hmac.new(b'secret', msg, hashlib.sha256).hexdigest()
            if platform == 'instagram':
                header = 'sha256=' + header
            self.assertTrue(webhook.signature(platform, 'secret', raw, header))
            self.assertFalse(webhook.signature(platform, 'secret', raw + b' ', header))
            self.assertFalse(webhook.signature(platform, 'secret', raw, 'wrong'))
        self.assertFalse(webhook.signature('instagram', 'secret', b'x' * 524289, 'wrong'))

    def test_challenge_verification(self):
        self.assertEqual(
            webhook.challenge(
                'instagram',
                'secret',
                'verify',
                {'hub.mode': 'subscribe', 'hub.verify_token': 'verify', 'hub.challenge': '123'},
            ),
            '123',
        )
        with self.assertRaises(ValueError):
            webhook.challenge(
                'instagram',
                'secret',
                'verify',
                {'hub.mode': 'subscribe', 'hub.verify_token': 'bad', 'hub.challenge': '123'},
            )
        answer = webhook.challenge('linkedin', 'secret', '', {'challengeCode': '123'})
        self.assertEqual(answer['challengeResponse'], hmac.new(b'secret', b'123', hashlib.sha256).hexdigest())

    def test_account_and_subscriber_scope(self):
        events = {'object': 'instagram', 'entry': [{'id': '100', 'time': 1}, {'id': 'OTHER', 'time': 2}]}
        self.assertEqual(len(webhook.hints('instagram', IG, json.dumps(events).encode())), 1)
        event = {
            'notificationId': 1,
            'lastModifiedAt': 2,
            'organizationalEntity': 'urn:li:organization:1',
            'subscriber': PROFILE['member'],
        }
        profile = {**PROFILE, 'id': 'urn:li:organization:1'}
        payload = {
            'type': 'ORGANIZATION_SOCIAL_ACTION_NOTIFICATIONS',
            'notifications': [event, {**event, 'subscriber': 'urn:li:person:OTHER'}],
        }
        self.assertEqual(len(webhook.hints('linkedin', profile, json.dumps(payload).encode())), 1)
        with self.assertRaises(ValueError):
            webhook.hints('linkedin', profile, b'{"type":"LEAD_ACTION"}')


