"""Install/upgrade and exercise real ORM in an isolated disposable database."""

import hashlib
import hmac
import json
import logging
import secrets
import sys
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import odoo
from odoo import api, fields
from odoo.exceptions import AccessError, UserError
from odoo.modules import db
from odoo.modules.registry import Registry
from odoo.tests import Form
from odoo.tools import config


def exercise(env, directory):
    from odoo.addons.omni_channel.tests.test_users import new_test_user
    from odoo.addons.omni_slack.providers import api as slack, vault
    from odoo.addons.omni_slack.models import test_setup

    check = TestCase()
    store, load, remove = vault.store, vault.load, vault.remove
    with (
        patch.object(type(env['ir.mail_server']), 'send_email', side_effect=AssertionError('Email blocked')),
        patch.object(
            type(env['res.users']), '_action_reset_password', side_effect=AssertionError('Invitations blocked')
        ),
        patch.object(
            slack,
            'verify',
            return_value={'team_id': 'TTEST', 'bot_id': 'BTEST', 'user_id': 'UBOT', 'name': 'Test workspace'},
        ),
        patch.object(vault, 'store', side_effect=lambda b: store(b, directory)),
        patch.object(vault, 'load', side_effect=lambda r, **s: load(r, data_dir=directory, **s)),
        patch.object(vault, 'remove', side_effect=lambda r, d: remove(r, d, directory)),
    ):
        manager = new_test_user(
            env, login='slack_manager', groups='omni_channel.group_omni_manager', company_id=env.company.id
        )
        operator = new_test_user(
            env, login='slack_operator', groups='omni_channel.group_omni_user', company_id=env.company.id
        )
        outsider = new_test_user(
            env, login='slack_outsider', groups='omni_channel.group_omni_manager', company_id=env.company.id
        )
        portal = new_test_user(env, login='slack_portal', groups='base.group_portal', company_id=env.company.id)
        team = env['omni.purpose'].create(
            {'name': 'Slack QA', 'code': 'slack_qa', 'user_ids': [fields.Command.set([manager.id, operator.id])]}
        )
        channels = env['omni.channel'].with_user(manager)
        draft = {
            'name': 'Slack QA',
            'company_id': env.company.id,
            'purpose_id': team.id,
            'channel_type_id': env.ref('omni_channel.channel_type_slack').id,
            'slack_test_received': False,
        }
        saved = channels.web_save(draft, {'id': {}, 'slack_test_received': {}})
        channel = channels.browse(saved[0]['id'])
        check.assertFalse(saved[0]['slack_test_received'])
        with Form(channels, view='omni_channel.channel_setup_form') as form:
            form.name = 'Native Slack form'
            form.channel_type_id = env.ref('omni_channel.channel_type_slack')
            form.company_id = env.company
            form.purpose_id = team
        for values in ({'slack_test_received': True}, {'slack_test_state': 'accepted'}):
            with check.assertRaises(AccessError):
                channels.create(draft | values)
        with check.assertRaises(AccessError):
            channels.with_context(default_slack_test_state='accepted').create(draft)
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                channel.with_user(user).action_slack_connect('xoxb-synthetic', 'a' * 32, 'ATEST')
        channel.action_setup_complete_step(0)
        channel.action_slack_connect('xoxb-synthetic', 'a' * 32, 'ATEST')
        channel.action_setup_complete_step(1)
        endpoint = channel.setup_endpoint_id
        url = 'https://channels.example.org/omni/inbound/' + endpoint.route_key
        endpoint.write({'webhook_url_override': url})
        with check.assertRaises(UserError):
            channel.action_setup_enable_receiving()
        stamp = str(int(fields.Datetime.now().timestamp()))

        def signed(value):
            raw = json.dumps(value).encode()
            signature = 'v0=' + hmac.new(b'a' * 32, b'v0:' + stamp.encode() + b':' + raw, hashlib.sha256).hexdigest()
            return raw, {'X-Slack-Signature': signature, 'X-Slack-Request-Timestamp': stamp}

        raw, headers = signed({'type': 'url_verification', 'challenge': 'synthetic'})
        with check.assertRaises(ValueError):
            endpoint.sudo()._slack_challenge(raw, {}, url)
        check.assertEqual(endpoint.sudo()._slack_challenge(raw, headers, url), 'synthetic')
        with check.assertRaises(AccessError):
            endpoint.write({'slack_verified_url': url})
        channel.action_setup_enable_receiving()
        channel.action_setup_complete_step(2)
        channel.action_setup_complete_step(3)
        value = {
            'type': 'event_callback',
            'team_id': 'TTEST',
            'api_app_id': 'ATEST',
            'event_id': 'EvTEST',
            'event': {
                'type': 'message',
                'channel_type': 'im',
                'channel': 'DTEST',
                'user': 'UTEST',
                'text': 'Hello',
                'ts': stamp + '.000001',
            },
        }
        raw, headers = signed(value)
        endpoint.sudo()._receive(raw, headers)
        endpoint.sudo()._receive(raw, headers)
        events = env['omni.webhook.event'].search([('endpoint_id', '=', endpoint.id)])
        check.assertEqual(len(events), 1)
        events._process_one()
        check.assertEqual(env['omni.message'].search_count([('conversation_id.channel_id', '=', channel.id)]), 1)
        from odoo.addons.omni_slack.providers.adapter import SlackAdapter
        from odoo.addons.omni_channel.providers.dispatch import DispatchClaim

        payload = {
            'operation': 'message.send',
            'account': 'BTEST',
            'sender': 'BTEST',
            'recipient': 'UTEST',
            'body': 'Approved reply',
            'conversation': {'namespace': 'TTEST', 'endpoint': 'BTEST', 'thread': 'DTEST', 'identity': 'UTEST'},
        }
        adapter = SlackAdapter()
        cfg = channel.setup_sender_id._health_config()
        claim = DispatchClaim(
            1,
            1,
            'synthetic',
            'synthetic',
            'slack',
            json.dumps(payload),
            'BTEST',
            'TTEST',
            'BTEST',
            channel.setup_account_id.credential_reference,
            json.dumps(cfg['adapter']),
        )

        def fake_api(method, token, values):
            if method == 'conversations.info':
                return {'ok': True, 'channel': {'id': 'DTEST', 'is_im': True, 'user': 'UTEST'}}
            check.assertEqual(values['text'], 'Approved reply')
            return {'ok': True, 'channel': 'DTEST', 'ts': stamp + '.000002'}

        with patch.object(slack, 'call', side_effect=fake_api):
            check.assertTrue(adapter.validate_command(payload, cfg))
            check.assertEqual(adapter.dispatch(claim).outcome, 'accepted')
            check.assertFalse(adapter.validate_command(payload | {'recipient': 'UOTHER'}, cfg))
        with patch.object(
            slack, 'call', return_value={'ok': True, 'channel': {'id': 'DTEST', 'is_im': False, 'user': 'UTEST'}}
        ):
            check.assertFalse(adapter.validate_command(payload, cfg))
        print('PASS: reply execution binds account, workspace, conversation and private recipient', flush=True)
        channel.write({'slack_tester_id': 'UTEST'})
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                channel.with_user(user)._claim_slack_test()
        with (
            patch.object(type(env['omni.blocked.identity']), '_matches', return_value=True),
            check.assertRaises(UserError),
        ):
            channel._claim_slack_test()
        with check.assertRaises(UserError):
            channel.action_setup_complete_step(4)
        env.cr.commit()  # ONLY this disposable database; public test action uses committed cursors.

        def fake_send(token, recipient):
            with env.registry.cursor() as cr:
                record = api.Environment(cr, api.SUPERUSER_ID, {})['omni.channel'].browse(channel.id)
                check.assertEqual(record.slack_test_state, 'pending')
            check.assertEqual(recipient, 'DTEST')
            return 'accepted', 'synthetic'

        with patch.object(test_setup, 'send_test', side_effect=fake_send) as send:
            channel.action_slack_send_test()
            env.cr.rollback()
            channel.invalidate_recordset()
            check.assertEqual(channel.slack_test_state, 'accepted')
            with check.assertRaises(UserError):
                channel.action_slack_send_test()
            check.assertEqual(send.call_count, 1)
        channel.write({'slack_test_received': True})
        channel.action_setup_complete_step(4)
        check.assertEqual(channel.setup_completed_steps, 5)
        check.assertEqual(channel.selected_sender_id, channel.setup_sender_id)
        check.assertFalse(channel.dispatch_enabled)
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                channel.with_user(user).action_slack_enable_replies()
        with check.assertRaises(UserError):
            channel.action_slack_enable_replies()
        policy = env['approval.center.policy'].create(
            {
                'name': 'Slack reply policy',
                'company_id': env.company.id,
                'approver_ids': [fields.Command.create({'user_id': manager.id, 'required': True})],
            }
        )
        channel.write({'approval_type_id': policy.id})
        channel.action_slack_enable_replies()
        check.assertTrue(channel.dispatch_enabled)
        channel.action_pause_dispatch()
        check.assertFalse(channel.dispatch_enabled)
        channel.write({'slack_test_received': False})
        check.assertFalse(channel.selected_sender_id)
        check.assertEqual(channel.setup_completed_steps, 4)
        with check.assertRaises(UserError):
            endpoint.write({'webhook_url_override': url.replace('channels.', 'new.')})
        print(
            'PASS: native Form, scopes, result forgery, signed challenge, dedup/inbox, blocked tester, durable claim, no resend, completion and receipt withdrawal',
            flush=True,
        )


def main():
    database = 'slack_qa_' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='slack-qa-') as directory:
        config.parse_config(
            [
                '-c',
                str(ROOT / 'odoo.conf'),
                '--data-dir',
                directory,
                '--no-http',
                '--log-level',
                'critical',
                '--log-handler',
                'py.warnings:ERROR',
            ],
            setup_logging=True,
        )
        logging.basicConfig(level=logging.CRITICAL)
        with (
            patch('requests.Session.get', side_effect=AssertionError('External GET blocked')),
            patch('requests.Session.post', side_effect=AssertionError('External POST blocked')),
        ):
            try:
                db.create(database, demo=False, user_password=secrets.token_urlsafe(32), lang='en_US')
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env['ir.module.module'].search([('name', '=', 'omni_slack')]).button_immediate_install()
                registry = Registry(database)
                with registry.cursor() as cr:
                    env = api.Environment(cr, api.SUPERUSER_ID, {})
                    env.ref('omni_channel.channel_setup_form')._check_xml()
                    env['ir.module.module'].search([('name', '=', 'omni_slack')]).button_immediate_upgrade()
                registry = Registry(database)
                with registry.cursor() as cr:
                    exercise(api.Environment(cr, api.SUPERUSER_ID, {}), directory)
            finally:
                if db.exist(database):
                    db.drop(database)
                print('Disposable Slack database removed', flush=True)


if __name__ == '__main__':
    main()
