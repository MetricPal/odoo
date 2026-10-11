import base64
import copy
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('teams_protocol_test');package.__path__=[str(ROOT/'providers')];sys.modules[package.__name__]=package

def load(name):
    spec=importlib.util.spec_from_file_location(package.__name__+'.'+name,ROOT/'providers'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module
api,vault,webhook=(load(n) for n in ('api','vault','webhook'))
APP='11111111-1111-1111-1111-111111111111'
TENANT='22222222-2222-2222-2222-222222222222'
USER='33333333-3333-3333-3333-333333333333'
NOW=1791676800
PRIVATE=rsa.generate_private_key(public_exponent=65537,key_size=2048)
def enc(raw):return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
def number(n):return enc(n.to_bytes((n.bit_length()+7)//8,'big'))
PUBLIC=PRIVATE.public_key().public_numbers()
KEY={'kid':'synthetic','kty':'RSA','use':'sig','n':number(PUBLIC.n),'e':number(PUBLIC.e),'endorsements':['msteams']}

def fixture():
    return {'type':'message','id':'synthetic-1','channelId':'msteams','serviceUrl':'https://smba.trafficmanager.net/amer/',
        'from':{'id':'29:synthetic','aadObjectId':USER,'name':'Tester'},'recipient':{'id':'28:'+APP},
        'conversation':{'id':'a:synthetic','conversationType':'personal'},'text':'Hello 👋','textFormat':'plain',
        'timestamp':'2026-10-11T00:00:00Z','channelData':{'tenant':{'id':TENANT}}}
def jwt(claim_changes=None,header_changes=None):
    header={'alg':'RS256','typ':'JWT','kid':'synthetic'}|(header_changes or {})
    claims={'iss':webhook.ISSUER,'aud':APP,'nbf':NOW-60,'exp':NOW+3600,'serviceurl':fixture()['serviceUrl']}|(claim_changes or {})
    parts=enc(json.dumps(header).encode())+'.'+enc(json.dumps(claims).encode())
    return parts+'.'+enc(PRIVATE.sign(parts.encode(),padding.PKCS1v15(),hashes.SHA256()))
def auth(value=None,claims=None,header=None,keys=None):
    raw=json.dumps(fixture() if value is None else value).encode()
    return webhook.authenticate(raw,{'Authorization':'Bearer '+jwt(claims,header)},APP,TENANT,keys=[KEY] if keys is None else keys,now=NOW)

class Protocol(unittest.TestCase):
    def test_valid_rs256_personal_text(self):
        key,message=webhook.message(auth());self.assertEqual(message['user'],USER);self.assertEqual(message['text'],'Hello 👋')
    def test_wrong_issuer_audience_expiry_and_future(self):
        for changes in ({'iss':'evil'},{'aud':TENANT},{'exp':NOW-301,'nbf':NOW-1000},{'nbf':NOW+301},{'exp':False},{'exp':float('nan')}):
            with self.assertRaises(ValueError):auth(claims=changes)
    def test_algorithm_and_header_url_rejected(self):
        for changes in ({'alg':'none'},{'alg':'HS256'},{'jku':'https://evil'},{'crit':['evil']}):
            with self.assertRaises(ValueError):auth(header=changes)
    def test_missing_endorsement_and_unknown_key(self):
        for key in (KEY|{'endorsements':[]},KEY|{'kid':'different'},KEY|{'kty':'oct'}):
            with self.assertRaises(ValueError):auth(keys=[key])
    def test_signature_tampering(self):
        token=jwt();parts=token.split('.');parts[2]=('A' if parts[2][0]!='A' else 'B')+parts[2][1:]
        with self.assertRaises(Exception):webhook.authenticate(json.dumps(fixture()).encode(),{'Authorization':'Bearer '+'.'.join(parts)},APP,TENANT,keys=[KEY],now=NOW)
    def test_unsigned_request_rejected(self):
        with self.assertRaises(ValueError):webhook.authenticate(b'{}',{},APP,TENANT,keys=[KEY],now=NOW)
    def test_wrong_tenant_bot_and_channel(self):
        for key,data in (('channelData',{'tenant':{'id':APP}}),('recipient',{'id':'28:'+TENANT}),('channelId','webchat')):
            value=fixture();value[key]=data
            with self.assertRaises(ValueError):auth(value)
    def test_service_claim_and_allowlist(self):
        value=fixture();value['serviceUrl']='https://evil.example/'
        with self.assertRaises(ValueError):auth(value)
        for url in ('http://smba.trafficmanager.net/amer/','https://smba.trafficmanager.net.evil/amer/','https://user@smba.trafficmanager.net/amer/','https://smba.trafficmanager.net/amer/?x=1','https://smba.trafficmanager.net/../evil'):
            with self.assertRaises(ValueError):api.service_url(url)
    def test_duplicate_keys(self):
        raw=b'{"channelId":"msteams","channelId":"webchat"}'
        with self.assertRaises(ValueError):webhook.authenticate(raw,{'Authorization':'Bearer '+jwt()},APP,TENANT,keys=[KEY],now=NOW)
    def test_group_file_and_nontext_ignored(self):
        for changes in ({'conversation':{'id':'a:synthetic','conversationType':'groupChat'}},{'attachments':[{'contentType':'image/png'}]},{'type':'typing'}):
            self.assertIsNone(webhook.message(fixture()|changes)[1])
    def test_html_alternate_never_rendered(self):
        value=fixture()|{'attachments':[{'contentType':'text/html','content':'<script>bad</script>'}]}
        self.assertEqual(webhook.message(value)[1]['text'],'Hello 👋')
    def test_personal_identity_required(self):
        value=fixture();value['from'].pop('aadObjectId')
        with self.assertRaises(ValueError):webhook.message(value)
    def test_size_bound(self):
        with self.assertRaises(ValueError):webhook.authenticate(b'x'*(1024*1024+1),{},APP,TENANT,keys=[KEY],now=NOW)
    def test_fixed_tenant_token_endpoint(self):
        with patch.object(api,'request_json',return_value=(200,{'token_type':'Bearer','access_token':'synthetic'})) as request:
            self.assertEqual(api.token(TENANT,APP,'synthetic-secret'),'synthetic')
            self.assertEqual(request.call_args.args[1],'https://login.microsoftonline.com/'+TENANT+'/oauth2/v2.0/token')
            self.assertEqual(request.call_args.kwargs['data']['scope'],'https://api.botframework.com/.default')
    def test_token_failure_does_not_send(self):
        with patch.object(api,'token',side_effect=ValueError),patch.object(api,'request_json') as request:
            self.assertEqual(api.send_test({'tenant_id':TENANT,'app_id':APP,'secret':'synthetic'},webhook.message(fixture())[1]|{'thread':'a:synthetic'})[0],'failed')
            request.assert_not_called()
    def test_send_outcomes_no_repeat(self):
        route={'service_url':fixture()['serviceUrl'],'thread':'a:synthetic','member_id':'29:synthetic'}
        for response,state in (((201,{'id':'synthetic'}),'accepted'),((400,{'error':{'code':'bad'}}),'failed'),((500,{'error':{}}),'unknown'),((200,{}),'unknown')):
            with patch.object(api,'token',return_value='synthetic'),patch.object(api,'request_json',return_value=response) as request:
                self.assertEqual(api.send_test({'tenant_id':TENANT,'app_id':APP,'secret':'secret'},route)[0],state)
                self.assertEqual(request.call_count,1)
                self.assertEqual(request.call_args.kwargs['json']['text'],api.TEST_MESSAGE)
    def test_timeout_never_retries(self):
        with patch.object(api,'token',return_value='synthetic'),patch.object(api,'request_json',side_effect=TimeoutError) as request:
            self.assertEqual(api.send_test({'tenant_id':TENANT,'app_id':APP,'secret':'secret'},{'service_url':fixture()['serviceUrl'],'thread':'a:synthetic','member_id':'29:synthetic'})[0],'unknown')
            self.assertEqual(request.call_count,1)
    def test_vault_encrypted_and_scoped(self):
        bundle={'database':'test','company_id':1,'purpose_id':2,'app_id':APP,'tenant_id':TENANT,'secret':'synthetic-secret'}
        with tempfile.TemporaryDirectory() as directory:
            ref=vault.store(bundle,directory)
            scope={k:bundle[k] for k in ('database','company_id','purpose_id','app_id','tenant_id')}
            self.assertEqual(vault.load(ref,data_dir=directory,**scope),bundle)
            for key in ('company_id','purpose_id','app_id','tenant_id'):
                with self.assertRaises(ValueError):vault.load(ref,data_dir=directory,**(scope|{key:'wrong'}))
            self.assertNotIn(b'synthetic-secret',next(Path(directory).rglob('*.bin')).read_bytes())
    def test_key_discovery_does_not_follow_untrusted_url(self):
        webhook._cache.clear()
        with patch.object(webhook,'request_json',return_value=(200,{'issuer':webhook.ISSUER,'jwks_uri':'https://evil','id_token_signing_alg_values_supported':['RS256']})) as request:
            with self.assertRaises(ValueError):webhook.signing_keys('synthetic')
            self.assertEqual(request.call_count,1)
        webhook._cache.clear()
