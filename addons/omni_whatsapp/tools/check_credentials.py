"""Run in an Odoo shell with an installed addon. All test records roll back."""
import json
import hashlib
import hmac
import tempfile
import unittest
import uuid
import os
import threading
import traceback
from contextlib import nullcontext
from unittest.mock import patch

from odoo import fields
from odoo.tests import Form
from odoo import api
from psycopg2.errors import SerializationFailure
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.tests.test_users import new_test_user
from odoo.addons.omni_whatsapp.models import credentials
from odoo.addons.omni_whatsapp.providers import vault
from odoo.addons.omni_whatsapp.providers.connection import PhoneNumber
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response
from types import SimpleNamespace

assert "env" in globals(), "Execute this check inside an Odoo shell"
real_transactions = globals().get('real_transactions', False)
assert not real_transactions or env.cr.dbname.startswith('wa_qa_'), 'Committed checks require a disposable database'
check = unittest.TestCase()
suffix = uuid.uuid4().hex
original_store, original_load, original_remove = vault.store, vault.load, vault.remove

with tempfile.TemporaryDirectory() as directory, \
     patch.object(type(env["ir.mail_server"]), "send_email", side_effect=AssertionError("Email blocked")), \
     patch.object(type(env["res.users"]), "_action_reset_password", side_effect=AssertionError("Invitations blocked")), \
     patch("requests.Session.get", side_effect=AssertionError("Live Meta blocked")), \
     patch("requests.Session.post", side_effect=AssertionError("Live Meta sends blocked")), \
     patch.object(credentials, "numbers", return_value=(PhoneNumber("234567890", "Sales", "+60 12 345 6789"),)), \
     patch.object(vault, "store", side_effect=lambda bundle: original_store(bundle, directory)), \
     patch.object(vault, "load", side_effect=lambda reference, **scope: original_load(reference, data_dir=directory, **scope)), \
     patch.object(vault, "remove", side_effect=lambda reference, database: original_remove(reference, database, directory)):
    try:
        manager = new_test_user(env, login="wa_manager_" + suffix, groups="omni_channel.group_omni_manager", company_id=env.company.id)
        operator = new_test_user(env, login="wa_operator_" + suffix, groups="omni_channel.group_omni_user", company_id=env.company.id)
        outsider = new_test_user(env, login="wa_outsider_" + suffix, groups="omni_channel.group_omni_manager", company_id=env.company.id)
        portal = new_test_user(env, login="wa_portal_" + suffix, groups="base.group_portal", company_id=env.company.id)
        team = env["omni.purpose"].create({"name": "WhatsApp test team", "code": "wa_" + suffix,
                                        "user_ids": [fields.Command.set([manager.id, operator.id])]})
        channels = env['omni.channel'].with_user(manager)
        draft = {'name': 'WhatsApp test', 'company_id': env.company.id,
                 'purpose_id': team.id, 'channel_type_id': env.ref('omni_channel.channel_type_whatsapp').id,
                 'whatsapp_test_received': False, 'whatsapp_tester_phone': False}
        saved = channels.web_save(draft, {'id': {}, 'whatsapp_test_received': {}})
        channel = channels.browse(saved[0]['id'])
        check.assertFalse(saved[0]['whatsapp_test_received'])
        with check.assertRaises(AccessError):
            channels.web_save({**draft, 'whatsapp_test_received': True}, {'id': {}})
        with check.assertRaises(AccessError):
            channels.with_context(default_whatsapp_test_received=True).web_save(draft, {'id': {}})
        with check.assertRaises(AccessError):
            channels.web_save({**draft, 'whatsapp_test_state': 'accepted'}, {'id': {}})
        with check.assertRaises(AccessError):
            channels.with_context(default_whatsapp_test_state='accepted').web_save(draft, {'id': {}})
        neutral = channels.with_context(default_whatsapp_test_received=False).web_save(
            {**draft, 'name': 'WhatsApp neutral default'}, {'id': {}, 'whatsapp_test_received': {}})
        check.assertFalse(neutral[0]['whatsapp_test_received'])
        print('Passed: native web_save accepts unchecked draft receipt; forged results and receipt defaults remain blocked')
        with Form(channels, view='omni_channel.channel_setup_form') as form:
            form.name = 'WhatsApp native form'
            form.channel_type_id = env.ref('omni_channel.channel_type_whatsapp')
            form.company_id = env.company
            form.purpose_id = team
        check.assertFalse(form.record.whatsapp_test_received)
        print('Passed: native Form defaults/onchange/create save a WhatsApp draft')
        channel.action_setup_complete_step(0)
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                channel.with_user(user).action_whatsapp_verify_account("123456789", "synthetic-token")
        print("Passed: operator, outsider and portal cannot verify credentials")
        profiles = channel.action_whatsapp_verify_account("123456789", "synthetic-token")
        check.assertEqual(profiles[0]["id"], "234567890")
        check.assertFalse(channel.setup_account_id)
        print("Passed: Verify is read-only and returns only public phone details")
        with check.assertRaises(UserError):
            channel.action_whatsapp_save_connection("123456789", "synthetic-token", "999")
        check.assertFalse(channel.setup_account_id)
        channel.action_whatsapp_save_connection("123456789", "synthetic-token", "234567890")
        account = channel.setup_account_id
        check.assertEqual(account._whatsapp_credentials()["access_token"], "synthetic-token")
        check.assertNotIn("synthetic-token", json.dumps(account.read()[0], default=str))
        check.assertNotIn("synthetic-token", json.dumps(channel.whatsapp_credentials_ui))
        print("Passed: selected phone is scoped; token encrypted outside ORM fields")
        channel.action_setup_complete_step(1)
        check.assertEqual(channel.setup_completed_steps, 2)
        check.assertTrue(channel.setup_endpoint_id)
        check.assertNotEqual(channel.setup_endpoint_id.state, 'enabled')
        check.assertFalse(channel.dispatch_enabled)
        print("Passed: Credentials completes without intake or dispatch activation")
        endpoint = channel.setup_endpoint_id
        url = 'https://channels.synthetic.example/omni/inbound/' + endpoint.route_key
        app_secret = 'a' * 32
        for user in (operator, outsider, portal):
            with check.assertRaises(AccessError):
                channel.with_user(user).action_whatsapp_save_webhook(url, app_secret)
        for invalid in (url.replace('https:', 'http:'), url + '?db=other', url.replace(endpoint.route_key, 'foreign')):
            with check.assertRaises(UserError):
                channel.action_whatsapp_save_webhook(invalid, app_secret)
        channel.action_whatsapp_save_webhook(url, app_secret)
        check.assertNotIn(app_secret, json.dumps(channel.whatsapp_receiving_ui))
        check.assertNotIn(app_secret, json.dumps(account.read()[0], default=str))
        check.assertNotIn(app_secret, json.dumps(env['omni.audit.event'].sudo().search([('purpose_id','=',team.id)]).read(), default=str))
        with check.assertRaises(UserError):
            channel.action_setup_defer_receiving()
        with check.assertRaises(UserError):
            channel.action_setup_complete_step(2)
        with env.cr.savepoint(), check.assertRaises(UserError):
            channel.action_setup_enable_receiving()
        token = account._whatsapp_credentials()['verify_token']
        params = {'hub.mode':'subscribe', 'hub.verify_token':token, 'hub.challenge':'12345'}
        with check.assertRaises(AccessError):
            endpoint._whatsapp_challenge(params, url)
        with check.assertRaises(ValueError):
            endpoint.sudo()._whatsapp_challenge({**params, 'hub.verify_token':'wrong'}, url)
        with check.assertRaises(ValueError):
            endpoint.sudo()._whatsapp_challenge(params, url.replace('channels.synthetic', 'different'))
        check.assertFalse(endpoint._whatsapp_verified())
        check.assertEqual(endpoint.sudo()._whatsapp_challenge(params, url), '12345')
        check.assertTrue(endpoint._whatsapp_verified())
        check.assertNotEqual(endpoint.state, 'enabled')
        from odoo.addons.omni_whatsapp.controllers import webhook as controller
        def get_callback(parameters):
            fake_request = SimpleNamespace(env=env(user=env.ref('base.public_user').id), httprequest=Request(EnvironBuilder(
                path='/omni/inbound/' + endpoint.route_key, base_url='https://channels.synthetic.example/',
                query_string=parameters).get_environ()),
                make_response=lambda body, status=200, headers=None: Response(body, status=status, headers=headers))
            with patch.object(controller, 'request', fake_request):
                return controller.WhatsAppWebhook().challenge(endpoint.route_key)
        response = get_callback(params)
        check.assertEqual(response.status_code, 200)
        check.assertEqual(response.get_data(as_text=True), '12345')
        check.assertEqual(response.headers['Cache-Control'], 'no-store')
        check.assertEqual(get_callback({**params, 'db':'foreign'}).status_code, 404)
        check.assertEqual(get_callback([*params.items(), ('hub.verify_token', token)]).status_code, 404)
        check.assertEqual(get_callback({**params, 'hub.verify_token':'wrong'}).status_code, 403)
        print('Passed: GET controller returns only challenge, rejects duplicate/extra query parameters and bad token')
        for forged in ({'whatsapp_callback_checked_at': fields.Datetime.now()}, {'whatsapp_verified_url':url}):
            with check.assertRaises(AccessError):
                endpoint.write(forged)
        with check.assertRaises(AccessError):
            endpoint.with_context(default_whatsapp_callback_checked_at=fields.Datetime.now()).write({'name':'Forged'})
        channel.action_setup_enable_receiving()
        check.assertTrue(endpoint._allowed())
        check.assertTrue(channel.setup_connection_ready)
        with check.assertRaises(AccessError):
            endpoint.with_user(operator).write({'webhook_url_override':url.replace('channels.synthetic','forged.synthetic')})
        check.assertTrue(endpoint._allowed())
        check.assertFalse(channel.dispatch_enabled)
        channel.action_setup_complete_step(2)
        check.assertIn(2, channel.setup_completed_step_ids)
        print('Passed: role/scope/URL guards, encrypted app secret, challenge checks and explicit receiving authorization')
        from odoo.addons.omni_channel.providers.inbound import IngressRejected
        stamp = str(int(fields.Datetime.now().timestamp()))
        payload = {'object':'whatsapp_business_account','entry':[{'id':account.whatsapp_business_id,
            'changes':[{'field':'messages','value':{'messaging_product':'whatsapp',
            'metadata':{'phone_number_id':account.external_account_key},'messages':[{
            'id':'wamid.' + suffix,'from':'60123456789','type':'text','timestamp':stamp,
            'text':{'body':'Synthetic inbound test'}}]}}]}]}
        def deliver(data, secret=app_secret):
            raw = json.dumps(data).encode()
            signature = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            return endpoint.with_user(env.ref('base.public_user')).sudo()._receive(raw, {'X-Hub-Signature-256':signature})
        with check.assertRaises(IngressRejected):
            deliver(payload, 'wrong-secret')
        foreign_payload = json.loads(json.dumps(payload))
        foreign_payload['entry'][0]['changes'][0]['value']['metadata']['phone_number_id'] = '999'
        with check.assertRaises(IngressRejected):
            deliver(foreign_payload)
        deliver(payload)
        deliver(payload)
        events = env['omni.webhook.event'].sudo().search([('account_id','=',account.id)])
        check.assertEqual(len(events), 1)
        check.assertEqual(events.payload['body'], 'Synthetic inbound test')
        events._process_one()
        check.assertTrue(env['omni.conversation'].sudo().search_count([('channel_id','=',channel.id)]))
        print('Passed: signed POST uses native intake, rejects foreign phones, deduplicates retries and creates an inbox conversation')
        channel.action_setup_complete_step(3)
        with patch.dict(os.environ, {'OMNI_WHATSAPP_GRAPH_VERSION':'v99.0'}):
            for user in (operator, outsider, portal):
                with check.assertRaises(AccessError):
                    channel.with_user(user)._claim_whatsapp_test()
            channel.write({'whatsapp_tester_phone':'60123456780'})
            with check.assertRaises(UserError):
                channel._claim_whatsapp_test()
            channel.write({'whatsapp_tester_phone':'60123456789'})
            with check.assertRaises(UserError):
                channel.write({'whatsapp_test_received':True})
            with patch.object(type(env['omni.blocked.identity']), '_matches', return_value=True):
                with check.assertRaises(UserError):
                    channel._claim_whatsapp_test()
            arguments = channel._claim_whatsapp_test()
            check.assertEqual(arguments, ('v99.0',account.external_account_key,'synthetic-token','60123456789'))
            with check.assertRaises(UserError):
                channel._claim_whatsapp_test()
            with check.assertRaises(UserError):
                channel.write({'whatsapp_tester_phone':'99999999'})
            with check.assertRaises(AccessError):
                channel.write({'whatsapp_test_state':'accepted'})
            with check.assertRaises(UserError):
                channel.action_whatsapp_save_webhook(url.replace('channels.synthetic','pending.synthetic'))
            channel._finish_whatsapp_test('failed','rejected')
            from odoo.addons.omni_whatsapp.models import test_setup
            sequence = []
            def fake_send(*args):
                check.assertEqual(args, arguments)
                check.assertEqual(sequence, ['commit'])
                sequence.append('send')
                return 'unknown', 'unconfirmed'
            if real_transactions:
                # Only the disposable database may persist fixtures/claims.
                env.cr.commit()
                barrier = threading.Barrier(2)
                outcomes = []
                def committed_send(*args):
                    check.assertEqual(args, arguments)
                    with env.registry.cursor() as cr:
                        fresh = api.Environment(cr, manager.id, {})['omni.channel'].browse(channel.id)
                        check.assertEqual(fresh.whatsapp_test_state, 'pending')
                    return 'unknown', 'unconfirmed'
                def worker():
                    try:
                        with env.registry.cursor() as cr:
                            record = api.Environment(cr, manager.id, {})['omni.channel'].browse(channel.id)
                            barrier.wait(timeout=15)
                            record.action_whatsapp_send_test()
                        outcomes.append('sent')
                    except (UserError, SerializationFailure):
                        outcomes.append('blocked')
                    except Exception as error:
                        traceback.print_exc()
                        outcomes.append(type(error).__name__)
                with patch.object(test_setup, 'send_test', side_effect=committed_send) as send:
                    workers = [threading.Thread(target=worker) for _ in range(2)]
                    for thread in workers:
                        thread.start()
                    for thread in workers:
                        thread.join(timeout=30)
                    check.assertTrue(all(not thread.is_alive() for thread in workers))
                    check.assertEqual(sorted(outcomes), ['blocked', 'sent'])
                    check.assertEqual(send.call_count, 1)
                    env.cr.rollback()  # Refresh this session's repeatable-read snapshot.
                    env.invalidate_all()
                    check.assertEqual(channel.whatsapp_test_state, 'unknown')
                    with check.assertRaises(UserError):
                        channel.action_whatsapp_send_test()
                    check.assertEqual(send.call_count, 1)
                print('Passed: two real concurrent sessions issue one fake send; committed uncertain result survives caller rollback and blocks retries')
            else:
                # Keep checks in the user's development database rollback-only.
                with patch.object(env.registry, 'cursor', side_effect=lambda: nullcontext(env.cr)), \
                     patch.object(type(env.cr), 'commit', side_effect=lambda: sequence.append('commit')), \
                     patch.object(test_setup, 'send_test', side_effect=fake_send) as send:
                    channel.action_whatsapp_send_test()
                    check.assertEqual(sequence, ['commit','send','commit'])
                    with check.assertRaises(UserError):
                        channel.action_whatsapp_send_test()
                    check.assertEqual(send.call_count, 1)
            with check.assertRaises(UserError):
                channel._claim_whatsapp_test()
            with check.assertRaises(UserError):
                channel.action_setup_complete_step(4)
            with Form(channel, view='omni_channel.channel_setup_form') as receipt_form:
                receipt_form.whatsapp_test_received = True
            check.assertTrue(channel.whatsapp_test_received)
            print('Passed: native final-step Form can confirm receipt without writing protected results')
            from odoo.addons.omni_whatsapp.providers import adapter
            with patch.object(adapter, 'verify_account', return_value=(PhoneNumber(account.external_account_key,'Sales','+60123456789'),)):
                channel.action_setup_complete_step(4)
            check.assertEqual(channel.setup_completed_steps,5)
            check.assertEqual(channel.selected_sender_id,channel.setup_sender_id)
            check.assertEqual(channel.readiness,'ready')
            check.assertFalse(channel.dispatch_enabled)
            channel.write({'whatsapp_test_received':False})
            check.assertEqual(channel.setup_completed_steps,4)
            check.assertFalse(channel.selected_sender_id)
            with check.assertRaises(UserError):
                channel.action_setup_complete_step(4)
            channel.write({'whatsapp_test_received':True})
            with patch.object(adapter, 'verify_account', return_value=(PhoneNumber(account.external_account_key,'Sales','+60123456789'),)):
                channel.action_setup_complete_step(4)
            print('Passed: scoped recent tester, blocked/duplicate guards, safe retry only after rejection, receipt confirmation and native 5/5 sender selection')
        changed = url.replace('channels.synthetic', 'updated.synthetic')
        channel.action_whatsapp_save_webhook(changed)
        check.assertFalse(channel.selected_sender_id)
        check.assertFalse(channel.whatsapp_test_received)
        check.assertFalse(channel.whatsapp_test_state)
        check.assertFalse(endpoint._allowed())
        check.assertFalse(endpoint._whatsapp_verified())
        check.assertFalse(channel.setup_connection_ready)
        check.assertNotIn(2, channel.setup_completed_step_ids)
        with check.assertRaises(IngressRejected):
            deliver(payload)
        channel.action_whatsapp_save_webhook(changed, 'b' * 32)
        check.assertEqual(account._whatsapp_credentials()['app_secret'], 'b' * 32)
        check.assertEqual(account._whatsapp_credentials()['verify_token'], token)
        check.assertFalse(endpoint._whatsapp_verified())
        print('Passed: callback/secret changes disable receiving and invalidate verification')
        with check.assertRaises(UserError):
            channel.action_setup_validate_step(4)
        check.assertLess(channel.setup_completed_steps, 5)
        for forged in ({"whatsapp_phone_name": "Forged"}, {"whatsapp_verified_at": fields.Datetime.now()}):
            with check.assertRaises(AccessError):
                account.write(forged)
        with check.assertRaises(AccessError):
            account.with_context(default_whatsapp_phone_name="Forged").write({"name": "Other"})
        with check.assertRaises(AccessError):
            account.with_user(operator)._whatsapp_credentials()
        print("Passed: forged verification fields, context defaults and operator secret reads rejected")
        with check.assertRaises(UserError):
            channel.action_whatsapp_save_connection("123456789", "synthetic-token", "234567890")
        check.assertEqual(channel.setup_account_id, account)
        foreign = env["res.company"].create({"name": "WhatsApp other company"})
        with check.assertRaises(AccessError):
            channel.with_context(allowed_company_ids=[foreign.id]).action_whatsapp_verify_account("123456789", "synthetic-token")
        print("Passed: concurrent/repeated replacement and cross-company access blocked")
        other = env["omni.channel"].with_user(manager).create({"name": "Other provider", "company_id": env.company.id,
                    "purpose_id": team.id, "channel_type_id": env.ref("omni_channel.channel_type_slack").id})
        with check.assertRaises(UserError):
            other.action_whatsapp_verify_account("123456789", "synthetic-token")
        with check.assertRaises(UserError):
            other.action_setup_prepare_connection()
        print("Passed: non-WhatsApp provider uses original unsupported-setup path")
    finally:
        env.cr.rollback()
        print('No network or email sent; ' + ('disposable fixtures will be removed with the database' if real_transactions
              else 'all synthetic records and credential files rolled back'))
