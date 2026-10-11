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
import base64
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes
APP='11111111-1111-1111-1111-111111111111'
TENANT='22222222-2222-2222-2222-222222222222'
USER='33333333-3333-3333-3333-333333333333'
SERVICE='https://smba.trafficmanager.net/amer/'
PRIVATE=rsa.generate_private_key(public_exponent=65537,key_size=2048)
def enc(raw): return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
def number(n): return enc(n.to_bytes((n.bit_length()+7)//8,'big'))
PUBLIC=PRIVATE.public_key().public_numbers()
KEY={'kid':'synthetic','kty':'RSA','n':number(PUBLIC.n),'e':number(PUBLIC.e),'endorsements':['msteams']}


def exercise(env, directory):
    from odoo.addons.omni_channel.tests.test_users import new_test_user
    from odoo.addons.omni_channel.providers.inbound import IngressRejected
    from odoo.addons.omni_teams.providers import api as teams, vault, webhook
    from odoo.addons.omni_teams.models import test_setup
    check = TestCase()
    store, load, remove = vault.store, vault.load, vault.remove
    with patch.object(type(env['ir.mail_server']), 'send_email', side_effect=AssertionError('Email blocked')), \
         patch.object(type(env['res.users']), '_action_reset_password', side_effect=AssertionError('Invitations blocked')), \
         patch.object(teams, 'token', return_value='synthetic-access-token'), patch.object(webhook,'signing_keys',return_value=[KEY]), \
         patch.object(vault, 'store', side_effect=lambda b: store(b, directory)), \
         patch.object(vault, 'load', side_effect=lambda r, **s: load(r, data_dir=directory, **s)), \
         patch.object(vault, 'remove', side_effect=lambda r, d: remove(r, d, directory)):
        manager = new_test_user(env, login='teams_manager', groups='omni_channel.group_omni_manager', company_id=env.company.id)
        operator = new_test_user(env, login='teams_operator', groups='omni_channel.group_omni_user', company_id=env.company.id)
        outsider = new_test_user(env, login='teams_outsider', groups='omni_channel.group_omni_manager', company_id=env.company.id)
        portal = new_test_user(env, login='teams_portal', groups='base.group_portal', company_id=env.company.id)
        team = env['omni.purpose'].create({'name':'Teams QA','code':'teams_qa','user_ids':[fields.Command.set([manager.id,operator.id])]})
        channels = env['omni.channel'].with_user(manager)
        draft={'name':'Teams QA','company_id':env.company.id,'purpose_id':team.id,'channel_type_id':env.ref('omni_teams.channel_type_teams').id,'teams_test_received':False}
        saved=channels.web_save(draft,{'id':{},'teams_test_received':{}})
        channel=channels.browse(saved[0]['id'])
        check.assertFalse(saved[0]['teams_test_received'])
        with Form(channels, view='omni_channel.channel_setup_form') as form:
            form.name='Native Teams form'
            form.channel_type_id=env.ref('omni_teams.channel_type_teams')
            form.company_id=env.company
            form.purpose_id=team
        for values in ({'teams_test_received':True},{'teams_test_state':'accepted'}):
            with check.assertRaises(AccessError): channels.create(draft|values)
        with check.assertRaises(AccessError): channels.with_context(default_teams_test_state='accepted').create(draft)
        for user in (operator,outsider,portal):
            with check.assertRaises(AccessError): channel.with_user(user).action_teams_connect(APP,TENANT,'synthetic-secret')
        channel.action_setup_complete_step(0)
        channel.action_teams_connect(APP,TENANT,'synthetic-secret')
        channel.action_setup_complete_step(1)
        endpoint=channel.setup_endpoint_id
        url='https://channels.example.org/omni/inbound/'+endpoint.route_key
        endpoint.write({'webhook_url_override':url})
        channel.action_setup_enable_receiving()
        channel.action_setup_complete_step(2)
        channel.action_setup_complete_step(3)
        now=fields.Datetime.now()
        value={'type':'message','id':'synthetic-1','channelId':'msteams','serviceUrl':SERVICE,
            'from':{'id':'29:synthetic','aadObjectId':USER,'name':'QA Tester'},'recipient':{'id':'28:'+APP},
            'conversation':{'id':'a:synthetic','conversationType':'personal'},'text':'Hello','textFormat':'plain',
            'timestamp':now.isoformat()+'Z','channelData':{'tenant':{'id':TENANT}}}
        stamp=str(int(now.timestamp()))
        def signed(value):
            claims={'iss':webhook.ISSUER,'aud':APP,'nbf':int(stamp)-60,'exp':int(stamp)+3600,'serviceurl':SERVICE}
            parts=enc(json.dumps({'alg':'RS256','kid':'synthetic'}).encode())+'.'+enc(json.dumps(claims).encode())
            token=parts+'.'+enc(PRIVATE.sign(parts.encode(),padding.PKCS1v15(),hashes.SHA256()))
            return json.dumps(value).encode(),{'Authorization':'Bearer '+token}
        raw,headers=signed(value)
        with check.assertRaises(IngressRejected): endpoint.sudo()._receive(raw,{})
        endpoint.sudo()._receive(raw,headers)
        endpoint.sudo()._receive(raw,headers)
        events=env['omni.webhook.event'].search([('endpoint_id','=',endpoint.id)])
        check.assertEqual(len(events),1)
        events._process_one()
        check.assertEqual(env['omni.message'].search_count([('conversation_id.channel_id','=',channel.id)]),1)
        from odoo.addons.omni_teams.providers.adapter import TeamsAdapter
        from odoo.addons.omni_channel.providers.dispatch import DispatchClaim
        conversation=env['omni.conversation'].search([('channel_id','=',channel.id)],limit=1)
        check.assertEqual(conversation.display_name,'QA Tester')
        check.assertEqual(conversation.teams_service_url,SERVICE)
        with check.assertRaises(AccessError): conversation.with_user(manager).write({'teams_service_url':SERVICE})
        with check.assertRaises(AccessError): conversation.with_user(operator).write({'teams_member_id':'29:evil'})
        payload={'operation':'message.send','account':APP,'sender':APP,'recipient':USER,'body':'Approved reply',
            'conversation':{'namespace':TENANT,'endpoint':APP,'thread':'a:synthetic','identity':USER,
                            'app_id':APP,'service_url':SERVICE,'member_id':'29:synthetic'}}
        adapter=TeamsAdapter();cfg=channel.setup_sender_id._health_config()
        claim=DispatchClaim(1,1,'synthetic','synthetic','teams',json.dumps(payload),APP,TENANT,APP,
                            channel.setup_account_id.credential_reference,json.dumps(cfg['adapter']))
        with patch.object(teams,'request_json',return_value=(201,{'id':'synthetic-reply'})) as request:
            check.assertTrue(adapter.validate_command(payload,cfg))
            check.assertEqual(adapter.dispatch(claim).outcome,'accepted')
            check.assertEqual(request.call_args.kwargs['json']['text'],'Approved reply')
            check.assertFalse(adapter.validate_command(payload|{'recipient':APP},cfg))
        with check.assertRaises(ValueError): adapter.validate_command(payload|{'conversation':payload['conversation']|{'service_url':'https://evil.example/'}},cfg)
        channel.write({'setup_conversation_id':conversation.id})
        for user in (operator,outsider,portal):
            with check.assertRaises(AccessError): channel.with_user(user)._claim_teams_test()
        with patch.object(type(env['omni.blocked.identity']), '_matches', return_value=True),check.assertRaises(UserError): channel._claim_teams_test()
        with check.assertRaises(UserError): channel.action_setup_complete_step(4)
        env.cr.commit()  # ONLY this disposable database; public test action uses committed cursors.
        def fake_send(credentials, route):
            with env.registry.cursor() as cr:
                record=api.Environment(cr,api.SUPERUSER_ID,{})['omni.channel'].browse(channel.id)
                check.assertEqual(record.teams_test_state,'pending')
            check.assertEqual(route['thread'],'a:synthetic')
            check.assertEqual(route['identity'],USER)
            return 'accepted','synthetic'
        with patch.object(test_setup,'send_test',side_effect=fake_send) as send:
            channel.action_teams_send_test()
            env.cr.rollback()
            channel.invalidate_recordset()
            check.assertEqual(channel.teams_test_state,'accepted')
            with check.assertRaises(UserError): channel.action_teams_send_test()
            check.assertEqual(send.call_count,1)
        channel.write({'teams_test_received':True})
        channel.action_setup_complete_step(4)
        check.assertEqual(channel.setup_completed_steps,5)
        check.assertEqual(channel.selected_sender_id,channel.setup_sender_id)
        check.assertFalse(channel.dispatch_enabled)
        for user in (operator,outsider,portal):
            with check.assertRaises(AccessError): channel.with_user(user).action_teams_enable_replies()
        with check.assertRaises(UserError): channel.action_teams_enable_replies()
        policy=env['approval.center.policy'].create({'name':'Teams reply policy','company_id':env.company.id,'approver_ids':[fields.Command.create({'user_id':manager.id,'required':True})]})
        channel.write({'approval_type_id':policy.id})
        channel.action_teams_enable_replies()
        check.assertTrue(channel.dispatch_enabled)
        channel.action_pause_dispatch()
        check.assertFalse(channel.dispatch_enabled)
        channel.write({'teams_test_received':False})
        check.assertFalse(channel.selected_sender_id)
        check.assertEqual(channel.setup_completed_steps,4)
        with check.assertRaises(UserError): endpoint.write({'webhook_url_override':url.replace('channels.','new.')})
        print('PASS: native Form, scopes, result forgery, signed activity, dedup/inbox, blocked tester, durable claim, no resend, completion and receipt withdrawal',flush=True)


def main():
    database='teams_qa_'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='teams-qa-') as directory:
        config.parse_config(['-c',str(ROOT/'odoo.conf'),'--data-dir',directory,'--no-http','--log-level','critical','--log-handler','py.warnings:ERROR'],setup_logging=True)
        logging.basicConfig(level=logging.CRITICAL)
        with patch('requests.Session.get',side_effect=AssertionError('External GET blocked')),patch('requests.Session.post',side_effect=AssertionError('External POST blocked')):
            try:
                db.create(database,demo=False,user_password=secrets.token_urlsafe(32),lang='en_US')
                registry=Registry(database)
                with registry.cursor() as cr:
                    env=api.Environment(cr,api.SUPERUSER_ID,{})
                    env['ir.module.module'].search([('name','in',['omni_teams','omni_slack','omni_whatsapp','omni_telegram'])]).button_immediate_install()
                registry=Registry(database)
                with registry.cursor() as cr:
                    env=api.Environment(cr,api.SUPERUSER_ID,{})
                    env.ref('omni_channel.channel_setup_form')._check_xml()
                    env['ir.module.module'].search([('name','=','omni_teams')]).button_immediate_upgrade()
                registry=Registry(database)
                with registry.cursor() as cr:
                    exercise(api.Environment(cr,api.SUPERUSER_ID,{}),directory)
            finally:
                if db.exist(database): db.drop(database)
                print('Disposable Teams database removed',flush=True)

if __name__=='__main__': main()
