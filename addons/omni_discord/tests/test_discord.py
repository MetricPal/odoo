"""Discord: relay protocol, the relay program, replies, and setup to inbox."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import BaseCase, TransactionCase, new_test_user, tagged

from odoo.addons.omni_channel.providers.dispatch import DispatchClaim
from odoo.addons.omni_discord.providers import adapter as discord, relay, rest

BOT = '111111111111111111'
PERSON = '222222222222222222'
GUILD = '333333333333333333'
ROOM = '444444444444444444'
DM = '555555555555555555'
SECRET = 's' * 48

_spec = importlib.util.spec_from_file_location('discord_relay_tool',
                                               Path(__file__).resolve().parents[1] / 'tools' / 'discord_relay.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def message(mid='666666666666666661', channel=ROOM, guild=GUILD, author=PERSON, text='Hello bot', bot=False):
    return {'id': mid, 'channel_id': channel, 'guild_id': guild,
            'author': {'id': author, 'username': 'ann', 'global_name': 'Ann', 'bot': bot},
            'content': text, 'timestamp': datetime.now(UTC).isoformat()}


def batch(*items, bot_id=BOT, secret=SECRET, timestamp=None):
    raw = json.dumps({'bot_id': bot_id, 'messages': list(items)}).encode()
    return raw, relay.sign(secret, raw, timestamp)


@tagged('post_install', '-at_install')
class DiscordProtocol(BaseCase):
    def test_signed_batches_from_the_relay(self):
        raw, headers = batch(message(), message(mid='666666666666666662', channel=DM, guild=''),
                             message(mid='666666666666666663', channel='777777777777777777'),
                             message(mid='666666666666666664', bot=True))
        found = relay.messages(raw, headers, secret=SECRET, bot_id=BOT, allowed_channels={ROOM})
        self.assertEqual([(m.message_id, m.thread) for m in found],
                         [('666666666666666661', 'ch:' + ROOM), ('666666666666666662', 'dm:' + DM)])

    def test_rejections(self):
        raw, headers = batch(message())
        with self.assertRaises(relay.RelayRejected):
            relay.messages(raw, headers, secret='x' * 48, bot_id=BOT, allowed_channels={ROOM})
        old = batch(message(), timestamp=datetime.now(UTC).timestamp() - 3600)
        with self.assertRaises(relay.RelayRejected):
            relay.messages(*old, secret=SECRET, bot_id=BOT, allowed_channels={ROOM})
        other_bot = batch(message(), bot_id='999999999999999999')
        with self.assertRaises(relay.RelayRejected):
            relay.messages(*other_bot, secret=SECRET, bot_id=BOT, allowed_channels={ROOM})
        tampered = (raw.replace(b'Hello', b'Hallo'), headers)
        with self.assertRaises(relay.RelayRejected):
            relay.messages(*tampered, secret=SECRET, bot_id=BOT, allowed_channels={ROOM})

    def test_tool_signature_matches_odoo(self):
        raw = b'{"bot_id":"1","messages":[]}'
        self.assertEqual(tool.sign(SECRET, raw, 1792590000), relay.sign(SECRET, raw, 1792590000))
        self.assertIsNone(tool.to_relay(message(bot=True), BOT))
        self.assertIsNone(tool.to_relay(message(text='  '), BOT))
        self.assertEqual(tool.to_relay(message(), BOT)['content'], 'Hello bot')

    def test_forwarder_retries_then_gives_up_on_rejection(self):
        class Response:
            def __init__(self, status):
                self.status_code = status

        class Session:
            def __init__(self, statuses):
                self.statuses, self.calls = list(statuses), []
                self.trust_env = True

            def post(self, url, data, headers, timeout, allow_redirects):
                self.calls.append((url, data, headers))
                return Response(self.statuses.pop(0))

        flaky = Session([503, 200])
        forwarder = tool.Forwarder('https://odoo.example/omni/inbound/x', SECRET, BOT, session=flaky, sleep=lambda s: None)
        self.assertTrue(forwarder.send([tool.to_relay(message(), BOT)]))
        self.assertEqual(len(flaky.calls), 2)
        url, raw, headers = flaky.calls[1]
        found = relay.messages(raw, headers, secret=SECRET, bot_id=BOT, allowed_channels={ROOM})
        self.assertEqual(found[0].body, 'Hello bot')
        refused = Session([403])
        self.assertFalse(tool.Forwarder('u', SECRET, BOT, session=refused, sleep=lambda s: None).send([{}]))
        self.assertEqual(len(refused.calls), 1, 'a rejected batch is not retried')

    def test_gateway_session_forwards_new_messages(self):
        frames = [
            {'op': 10, 'd': {'heartbeat_interval': 41250}},
            {'op': 0, 's': 1, 't': 'READY', 'd': {'user': {'username': 'bot'}}},
            {'op': 0, 's': 2, 't': 'MESSAGE_CREATE', 'd': message()},
            {'op': 0, 's': 3, 't': 'MESSAGE_CREATE', 'd': message(mid='666666666666666669', bot=True)},
            {'op': 7, 'd': None},
        ]

        class Socket:
            def __init__(self):
                self.sent, self.closed = [], False

            def recv(self):
                return json.dumps(frames.pop(0))

            def send(self, text):
                self.sent.append(json.loads(text))

            def close(self):
                self.closed = True

        socket = Socket()
        forwarded = []

        class Forwarder:
            def send(self, items):
                forwarded.extend(items)

        gateway = tool.Gateway('bot-token', Forwarder(), BOT, connect=lambda: socket, sleep=lambda s: None)
        with patch.object(tool.threading, 'Thread'):
            gateway.session()
        identify = [f for f in socket.sent if f['op'] == 2][0]
        self.assertEqual(identify['d']['intents'], tool.INTENTS)
        self.assertEqual([m['id'] for m in forwarded], ['666666666666666661'])
        self.assertEqual(gateway.sequence, 3)
        self.assertTrue(socket.closed)

    def _payload(self, thread='ch:' + ROOM, **changes):
        base = {'operation': 'message.send', 'recipient': PERSON, 'body': 'Thanks!', 'account': BOT, 'sender': BOT,
                'conversation': {'namespace': BOT, 'endpoint': BOT, 'thread': thread, 'identity': PERSON}}
        base.update(changes)
        return base

    def test_replies_only_in_chosen_channels_and_dms(self):
        config = {'account_key': BOT, 'credential_reference': 'x', 'adapter': {'channels': [ROOM]}}

        def lookup(token, path, **kw):
            channel = path.rsplit('/', 1)[-1]
            if channel == DM:
                return {'id': DM, 'type': 1, 'recipients': [{'id': PERSON}]}
            return {'id': channel, 'type': 0}

        adapter = discord.DiscordAdapter(call=lookup)
        with patch.object(discord, 'bundle', return_value={'bot_token': 't'}):
            self.assertTrue(adapter.validate_command(self._payload(), config))
            self.assertTrue(adapter.validate_command(self._payload(thread='dm:' + DM), config))
            self.assertFalse(adapter.validate_command(self._payload(thread='ch:777777777777777777'), config))
            stranger = self._payload(thread='dm:' + DM, recipient='888888888888888888')
            stranger['conversation']['identity'] = '888888888888888888'
            self.assertFalse(adapter.validate_command(stranger, config))

    def test_dispatch_mentions_only_the_person_answered(self):
        sent = []

        def post(token, path, method='GET', body=None):
            sent.append((path, body))
            return {'id': '999999999999999991', 'channel_id': ROOM, 'author': {'id': BOT}}

        claim = DispatchClaim(command_id=1, attempt_id=1, token='t', command_uuid='u', provider='discord',
                              payload_json=json.dumps(self._payload()), account_key=BOT, namespace=BOT, sender_key=BOT,
                              credential_reference='OMNI_SECRET_DISCORD_X', adapter_config_json=json.dumps({'channels': [ROOM]}))
        with patch.object(discord, 'bundle', return_value={'bot_token': 't'}):
            result = discord.DiscordAdapter(call=post).dispatch(claim)
            self.assertEqual(result.outcome, 'accepted')
            self.assertEqual(sent[0][1]['content'], '<@%s> Thanks!' % PERSON)
            self.assertEqual(sent[0][1]['allowed_mentions'], {'parse': [], 'users': [PERSON]})

            def limited(token, path, method='GET', body=None):
                raise rest.RestError('rate_limited', retry_after=2.5)
            limited_result = discord.DiscordAdapter(call=limited).dispatch(claim)
            self.assertEqual((limited_result.outcome, limited_result.retryable), ('definitely_not_sent', True))

            def lost(token, path, method='GET', body=None):
                raise rest.RestError('network', sent=True)
            self.assertEqual(discord.DiscordAdapter(call=lost).dispatch(claim).outcome, 'unknown')


@tagged('post_install', '-at_install')
class DiscordSetup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='discord_manager', groups='omni_channel.group_omni_manager')
        cls.operator = new_test_user(cls.env, login='discord_operator', groups='omni_channel.group_omni_user')
        purpose = cls.env['omni.purpose'].create({'name': 'Community', 'code': 'community',
                                                  'user_ids': [fields.Command.set([cls.manager.id, cls.operator.id])]})
        cls.type = cls.env.ref('omni_channel.channel_type_discord')
        cls.channel = cls.env['omni.channel'].with_user(cls.manager).create(
            {'name': 'Community Discord', 'purpose_id': purpose.id, 'channel_type_id': cls.type.id})

    def _connect(self):
        with patch('odoo.addons.omni_discord.models.discord.rest.bot', return_value=(BOT, 'Helper bot')):
            return self.channel.with_user(self.manager).action_discord_save_connection('bot-token')

    def test_bot_connection(self):
        self.assertTrue(self.type.adapter_ready)
        with self.assertRaises(AccessError):
            self.channel.with_user(self.operator).action_discord_save_connection('bot-token')
        with patch('odoo.addons.omni_discord.models.discord.rest.bot', side_effect=rest.RestError('not_bot')), \
                self.assertRaisesRegex(UserError, 'does not belong to a bot'):
            self.channel.with_user(self.manager).action_discord_save_connection('user-token')
        self.assertEqual(self._connect(), {'bot': BOT, 'name': 'Helper bot'})
        self.assertEqual(self.channel.setup_account_id.discord_bot_name, 'Helper bot')

    def test_signed_relay_message_reaches_the_inbox(self):
        self._connect()
        channel = self.channel.with_user(self.manager)
        channel.action_setup_prepare_connection()
        endpoint = channel.setup_endpoint_id.sudo()
        url = 'https://community.example.com/omni/inbound/' + endpoint.route_key
        with self.assertRaisesRegex(UserError, 'channel IDs'):
            channel.action_discord_save_receiving(url, 'general')
        channel.action_discord_save_receiving(url, ROOM)
        ui = channel.discord_receiving_ui
        self.assertEqual(ui['channels'], ROOM)
        self.assertGreaterEqual(len(ui['secret']), 48)
        self.assertIn('discord_relay.py --url ' + url, ui['command'])
        channel.setup_policy_id.action_activate()
        endpoint.with_user(self.manager).action_enable()
        raw, headers = batch(message(text='When is the next event?'), secret=ui['secret'])
        endpoint._receive(raw, headers)
        self.env['omni.webhook.event']._process_batch()
        conversation = self.env['omni.conversation'].search([('endpoint_id', '=', endpoint.id)])
        self.assertEqual(conversation.thread_key, 'ch:' + ROOM)
        self.assertEqual(conversation.message_ids.body, 'When is the next event?')
        forged = batch(message(mid='666666666666666670'), secret='f' * 48)
        with self.assertRaises(Exception):
            endpoint._receive(*forged)
