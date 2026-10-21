"""Messenger: webhook protocol, reply window, dispatch and the full setup-to-inbox path."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import BaseCase, HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_channel.providers.dispatch import DispatchClaim
from odoo.addons.omni_messenger.providers import adapter as messenger, graph, webhook

PAGE = '1001'
SECRET = 'a' * 32
PERSON = '5551'


def signed(payload, secret=SECRET):
    raw = json.dumps(payload).encode()
    return raw, {'X-Hub-Signature-256': 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


def event(text='Hello Page', mid='m_1', sender=PERSON, echo=False, when=None):
    stamp = int((when or datetime.now(UTC)).timestamp() * 1000)
    message = {'mid': mid, 'text': text}
    if echo:
        message['is_echo'] = True
    return {'sender': {'id': sender}, 'recipient': {'id': PAGE}, 'timestamp': stamp, 'message': message}


def payload(*events, page=PAGE):
    return {'object': 'page', 'entry': [{'id': page, 'time': 1, 'messaging': list(events)}]}


@tagged('post_install', '-at_install')
class MessengerProtocol(BaseCase):
    def test_signed_text_messages_only(self):
        raw, headers = signed(payload(event(), event(echo=True, mid='m_2', sender=PAGE),
                                      {'sender': {'id': PERSON}, 'recipient': {'id': PAGE}, 'timestamp': 1,
                                       'read': {'watermark': 1}}))
        messages = webhook.text_messages(raw, headers, app_secret=SECRET, page_id=PAGE)
        self.assertEqual([(m.message_id, m.sender_id, m.body) for m in messages], [('m_1', PERSON, 'Hello Page')])

    def test_rejections(self):
        raw, headers = signed(payload(event()))
        with self.assertRaises(webhook.WebhookRejected):
            webhook.text_messages(raw, headers, app_secret='b' * 32, page_id=PAGE)
        other_page = signed(payload(event(), page='2002'))
        with self.assertRaises(webhook.WebhookRejected):
            webhook.text_messages(*other_page, app_secret=SECRET, page_id=PAGE)
        duplicate = signed(payload(event(), event()))
        with self.assertRaises(webhook.WebhookRejected):
            webhook.text_messages(*duplicate, app_secret=SECRET, page_id=PAGE)
        instagram = signed({'object': 'instagram', 'entry': []})
        with self.assertRaises(webhook.WebhookRejected):
            webhook.text_messages(*instagram, app_secret=SECRET, page_id=PAGE)

    def test_handshake(self):
        good = {'hub.mode': 'subscribe', 'hub.verify_token': 'tok', 'hub.challenge': '99'}
        self.assertEqual(webhook.verification_challenge(good, 'tok'), '99')
        with self.assertRaises(webhook.WebhookRejected):
            webhook.verification_challenge({**good, 'hub.verify_token': 'nope'}, 'tok')

    def _payload(self, **changes):
        base = {'operation': 'message.send', 'recipient': PERSON, 'body': 'Thanks!', 'account': PAGE, 'sender': PAGE,
                'conversation': {'namespace': PAGE, 'endpoint': PAGE, 'thread': PERSON, 'identity': PERSON}}
        base.update(changes)
        return base

    def test_reply_window_comes_from_meta(self):
        def fake(last):
            def call(token, path, **kw):
                self.assertEqual(path, '/%s/conversations' % PAGE)
                self.assertEqual(kw['params']['user_id'], PERSON)
                return {'data': [{'messages': {'data': [
                    {'from': {'id': PAGE}, 'created_time': datetime.now(UTC).isoformat()},
                    {'from': {'id': PERSON}, 'created_time': last.isoformat()},
                ]}}]}
            return call

        config = {'account_key': PAGE, 'credential_reference': 'x', 'adapter': {}}
        with patch.object(messenger, 'bundle', return_value={'access_token': 't'}):
            fresh = messenger.MessengerAdapter(call=fake(datetime.now(UTC) - timedelta(hours=2)))
            self.assertTrue(fresh.validate_command(self._payload(), config))
            stale = messenger.MessengerAdapter(call=fake(datetime.now(UTC) - timedelta(hours=25)))
            self.assertFalse(stale.validate_command(self._payload(), config), 'our own later message does not reopen it')
            self.assertFalse(fresh.validate_command(self._payload(recipient=PAGE), config))
            self.assertFalse(fresh.validate_command(self._payload(body='x' * 2001), config))

    def _claim(self, **changes):
        return DispatchClaim(command_id=1, attempt_id=1, token='t', command_uuid='u', provider='messenger',
                             payload_json=json.dumps(self._payload(**changes)), account_key=PAGE, namespace=PAGE,
                             sender_key=PAGE, credential_reference='OMNI_SECRET_MESSENGER_X',
                             adapter_config_json='{}')

    def test_dispatch_outcomes(self):
        sent = []

        def ok(token, path, **kw):
            sent.append((path, kw['body']))
            return {'recipient_id': PERSON, 'message_id': 'm_abc'}

        with patch.object(messenger, 'bundle', return_value={'access_token': 't'}):
            result = messenger.MessengerAdapter(call=ok).dispatch(self._claim())
            self.assertEqual(result.outcome, 'accepted')
            self.assertEqual(result.provider_message_key, PAGE + ':m_abc')
            self.assertEqual(sent[0][0], '/%s/messages' % PAGE)
            self.assertEqual(sent[0][1]['messaging_type'], 'RESPONSE')

            def lost(token, path, **kw):
                raise graph.GraphError('network', sent=True)
            self.assertEqual(messenger.MessengerAdapter(call=lost).dispatch(self._claim()).outcome, 'unknown')

            def refused(token, path, **kw):
                raise graph.GraphError('rejected', status=400)
            self.assertEqual(messenger.MessengerAdapter(call=refused).dispatch(self._claim()).outcome,
                             'definitely_not_sent')
            self.assertEqual(messenger.MessengerAdapter(call=ok).dispatch(self._claim(recipient='12')).outcome,
                             'definitely_not_sent')


class MessengerFixture:
    @classmethod
    def _fixture(cls):
        cls.manager = new_test_user(cls.env, login='msgr_manager', groups='omni_channel.group_omni_manager')
        cls.operator = new_test_user(cls.env, login='msgr_operator', groups='omni_channel.group_omni_user')
        cls.purpose = cls.env['omni.purpose'].create({
            'name': 'Messenger care', 'code': 'messenger_care',
            'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id])],
        })
        cls.type = cls.env.ref('omni_messenger.channel_type_messenger')
        cls.channel = cls.env['omni.channel'].with_user(cls.manager).create({
            'name': 'Page inbox', 'purpose_id': cls.purpose.id, 'channel_type_id': cls.type.id,
        })

    def _connect(self):
        with patch('odoo.addons.omni_messenger.models.messenger.graph.page', return_value=(PAGE, 'Acme Page')):
            return self.channel.with_user(self.manager).action_messenger_save_connection('page-token')

    def _receiving(self):
        self._connect()
        channel = self.channel.with_user(self.manager)
        channel.action_setup_prepare_connection()
        endpoint = channel.setup_endpoint_id
        url = 'https://care.example.com/omni/inbound/' + endpoint.route_key
        channel.action_messenger_save_webhook(url, SECRET)
        return channel, endpoint.sudo(), url


@tagged('post_install', '-at_install')
class MessengerSetup(MessengerFixture, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()

    def test_catalogue_offers_messenger(self):
        self.assertTrue(self.type.adapter_ready)
        self.assertEqual(self.type.category, 'messaging')
        self.assertTrue(self.channel.is_messenger)

    def test_connect_page(self):
        with self.assertRaises(AccessError):
            self.channel.with_user(self.operator).action_messenger_save_connection('page-token')
        with patch('odoo.addons.omni_messenger.models.messenger.graph.page',
                   side_effect=graph.GraphError('page_token')), self.assertRaisesRegex(UserError, 'not a Page access token'):
            self.channel.with_user(self.manager).action_messenger_save_connection('user-token')
        self.assertEqual(self._connect(), {'page': PAGE, 'name': 'Acme Page'})
        account = self.channel.setup_account_id
        self.assertEqual(account.external_account_key, PAGE)
        self.assertEqual(account.messenger_page_name, 'Acme Page')
        credentials = account.with_user(self.manager)._messenger_credentials()
        self.assertEqual(credentials['access_token'], 'page-token')
        self.assertTrue(credentials['verify_token'])
        self.assertEqual(self.channel.with_user(self.manager).messenger_credentials_ui['name'], 'Acme Page')
        with self.assertRaises(AccessError):
            account.with_user(self.manager).write({'messenger_page_name': 'Forged'})

    def test_webhook_needs_secret_and_handshake(self):
        self._connect()
        channel = self.channel.with_user(self.manager)
        channel.action_setup_prepare_connection()
        endpoint = channel.setup_endpoint_id
        url = 'https://care.example.com/omni/inbound/' + endpoint.route_key
        with self.assertRaisesRegex(UserError, 'app secret'):
            channel.action_messenger_save_webhook(url, '')
        with self.assertRaisesRegex(UserError, 'public HTTPS'):
            channel.action_messenger_save_webhook('http://care.example.com/x', SECRET)
        channel.action_messenger_save_webhook(url, SECRET)
        ui = channel.messenger_receiving_ui
        self.assertTrue(ui['saved'])
        self.assertFalse(ui['verified'])
        with self.assertRaises(AccessError):
            endpoint._messenger_challenge({}, url)
        params = {'hub.mode': 'subscribe', 'hub.verify_token': ui['token'], 'hub.challenge': '777'}
        with self.assertRaises(ValueError):
            endpoint.sudo()._messenger_challenge({**params, 'hub.verify_token': 'wrong'}, url)
        self.assertEqual(endpoint.sudo()._messenger_challenge(params, url), '777')
        channel.invalidate_recordset(['messenger_receiving_ui'])
        self.assertTrue(channel.messenger_receiving_ui['verified'])
        with self.assertRaisesRegex(UserError, 'Turn on receiving first'):
            channel.action_setup_defer_receiving()

    def test_signed_message_reaches_the_inbox(self):
        channel, endpoint, url = self._receiving()
        token = channel.messenger_receiving_ui['token']
        endpoint._messenger_challenge({'hub.mode': 'subscribe', 'hub.verify_token': token, 'hub.challenge': '1'}, url)
        channel.setup_policy_id.action_activate()
        endpoint.with_user(self.manager).action_enable()
        raw, headers = signed(payload(event(text='Is the shop open today?')))
        endpoint._receive(raw, headers)
        self.env['omni.webhook.event']._process_batch()
        conversation = self.env['omni.conversation'].search([('endpoint_id', '=', endpoint.id)])
        self.assertEqual(len(conversation), 1)
        self.assertEqual(conversation.thread_key, PERSON)
        self.assertEqual(conversation.message_ids.body, 'Is the shop open today?')
        forged, headers = signed(payload(event(mid='m_9')), secret='b' * 32)
        with self.assertRaises(Exception):
            endpoint._receive(forged, headers)


@tagged('post_install', '-at_install')
class MessengerHandshakeRoute(MessengerFixture, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()

    def test_get_route_returns_only_the_challenge(self):
        channel, endpoint, _url = self._receiving()
        token = channel.messenger_receiving_ui['token']
        # Meta calls the public address; the test server answers on its own base URL.
        local = '%s/omni/inbound/%s' % (self.base_url(), endpoint.route_key)
        with patch.object(type(endpoint), '_get_webhook_url', lambda self: local):
            query = {'hub.mode': 'subscribe', 'hub.verify_token': token, 'hub.challenge': '4242'}
            response = self.url_open('/omni/inbound/%s?%s' % (endpoint.route_key, '&'.join(
                '%s=%s' % item for item in query.items())))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, '4242')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            bad = self.url_open('/omni/inbound/%s?hub.mode=subscribe&hub.verify_token=no&hub.challenge=1'
                                % endpoint.route_key)
            self.assertEqual(bad.status_code, 403)
            extra = self.url_open('/omni/inbound/%s?hub.mode=subscribe&hub.verify_token=%s&hub.challenge=1&db=x'
                                  % (endpoint.route_key, token))
            self.assertEqual(extra.status_code, 404)
        unknown = self.url_open('/omni/inbound/%s?hub.mode=subscribe&hub.verify_token=a&hub.challenge=1' % ('0' * 36))
        self.assertEqual(unknown.status_code, 404)
