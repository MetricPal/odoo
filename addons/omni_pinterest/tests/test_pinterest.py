"""Pinterest connector against a fake API v5, plus Social wiring."""

from unittest.mock import patch

from odoo import fields
from odoo.tests import BaseCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_pinterest.providers import api
from odoo.addons.omni_social.providers import registry
from odoo.addons.omni_social.providers.http import ProviderError

BOARDS = {'items': [{'id': '1001', 'name': 'Launches'}, {'id': '1002', 'name': 'Recipes'}]}
PROFILE = {'id': 'acme', 'name': 'acme · Launches', 'board': '1001', 'board_name': 'Launches', 'kind': 'organization'}
BUNDLE = {'token': 'tok', 'profile': PROFILE}
PHOTO = {'id': 1, 'kind': 'image', 'url': 'https://odoo.example/omni/social/media/t/0', 'alt_text': 'Box'}


class FakePinterest:
    def __init__(self, post_error=None):
        self.posts, self.post_error = [], post_error

    def __call__(self, host, path, token, *, method='GET', params=None, body=None, headers=None):
        assert host == 'api.pinterest.com'
        if method == 'POST':
            if self.post_error:
                raise self.post_error
            self.posts.append((path, body))
            return {'id': '900001'}, {}
        if path == '/v5/user_account':
            return {'username': 'acme', 'account_type': 'BUSINESS'}, {}
        if path == '/v5/boards':
            return BOARDS, {}
        if path == '/v5/boards/1001/pins':
            return {'items': [{'id': '800', 'title': 'Old pin', 'description': 'd', 'created_at': '2026-10-01T10:00:00'}]}, {}
        raise ProviderError('rejected')


def doc(**values):
    base = {'operation': 'post', 'account': 'acme', 'title': 'Our new box', 'body': 'See it at https://acme.example/box.',
            'format': 'standard', 'media': [PHOTO]}
    base.update(values)
    return base


@tagged('post_install', '-at_install')
class PinterestProtocol(BaseCase):
    def test_board_is_chosen_by_name_or_id(self):
        with patch.object(api, 'call', FakePinterest()):
            self.assertEqual(api.Adapter().verify('t', 'Launches')['board'], '1001')
            self.assertEqual(api.Adapter().verify('t', '1002')['board_name'], 'Recipes')
            for bad in ('', 'Nope'):
                with self.assertRaises(ValueError):
                    api.Adapter().verify('t', bad)

    def test_single_image_pin_with_link(self):
        graph = FakePinterest()
        with patch.object(api, 'call', graph):
            outcome, key, _note = api.Adapter().execute(BUNDLE, doc())
        self.assertEqual((outcome, key), ('sent', '900001'))
        path, body = graph.posts[0]
        self.assertEqual(path, '/v5/pins')
        self.assertEqual(body['board_id'], '1001')
        self.assertEqual(body['link'], 'https://acme.example/box')
        self.assertEqual(body['media_source'], {'source_type': 'image_url', 'url': PHOTO['url']})

    def test_multi_image_pin(self):
        graph = FakePinterest()
        media = [PHOTO, {**PHOTO, 'id': 2}]
        with patch.object(api, 'call', graph):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc(format='carousel', media=media))[0], 'sent')
        source = graph.posts[0][1]['media_source']
        self.assertEqual((source['source_type'], len(source['items'])), ('multiple_image_urls', 2))

    def test_uncertain_pin_is_not_repeated(self):
        with patch.object(api, 'call', FakePinterest(post_error=ProviderError('network', True))):
            self.assertEqual(api.Adapter().execute(BUNDLE, doc())[0], 'unknown')

    def test_validation(self):
        adapter = api.Adapter()
        for bad in (doc(media=[]), doc(title=''), doc(title='x' * 101), doc(body='x' * 501),
                    doc(format='carousel', media=[PHOTO]), doc(media=[{**PHOTO, 'kind': 'video'}]),
                    doc(operation='reply')):
            with self.assertRaises(ValueError):
                adapter.validate(bad)
        self.assertEqual(api.link_of('no link here'), '')

    def test_read_board_pins(self):
        with patch.object(api, 'call', FakePinterest()):
            items, note = api.Adapter().read(BUNDLE)
        self.assertEqual(items[0]['permalink'], 'https://www.pinterest.com/pin/800/')
        self.assertIn('no comments API', note)


@tagged('post_install', '-at_install')
class PinterestInSocial(TransactionCase):
    def test_card_and_reviewed_title(self):
        card = self.env.ref('omni_channel.channel_type_pinterest')
        self.assertTrue(card.social_ready)
        caps = registry.capabilities('pinterest')
        self.assertEqual((caps.operations, caps.oauth.client_auth, caps.title_limit), (('post',), 'basic', 100))
        manager = new_test_user(self.env, login='pin_mgr', groups='omni_channel.group_omni_manager')
        team = self.env['omni.purpose'].create({'name': 'Pin QA', 'code': 'pin_qa',
                                                'user_ids': [fields.Command.set(manager.ids)]})
        account = self.env['omni.social.connection'].with_user(manager).create(
            {'name': 'Pinterest', 'provider': 'pinterest', 'purpose_id': team.id})
        self.assertEqual(account.credentials_ui['account_label'], 'Board to pin to (name or ID)')
        self.assertTrue(account.credentials_ui['account_required'])
        with patch.object(api, 'call', FakePinterest()):
            account.action_connect('synthetic', 'Launches')
        self.assertEqual(account.profile_name, 'acme · Launches')
        post = self.env['omni.social.publication'].with_user(manager).create(
            {'name': 'Our new box', 'connection_id': account.id, 'body': 'Text', 'reason': 'QA'})
        with patch.object(api.Adapter, 'validate'), patch.object(type(post), '_check_capabilities'):
            self.assertEqual(post._document('t')['title'], 'Our new box')
