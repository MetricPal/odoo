import hashlib
import hmac
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location('slack_test_' + name, ROOT / 'providers' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
webhook, api, vault = (load(n) for n in ('webhook','api','vault'))
NOW=1791676800
SECRET='a'*32

def fixture(**changes):
    event={'type':'message','channel_type':'im','channel':'DTEST','user':'UTEST','text':'Hello 👋','ts':str(NOW)+'.000001'}
    event.update(changes)
    return {'type':'event_callback','team_id':'TTEST','api_app_id':'ATEST','event_id':'EvTEST','event':event}

def sign(raw, stamp=None):
    stamp=str(NOW if stamp is None else stamp)
    return {'X-Slack-Request-Timestamp':stamp,'X-Slack-Signature':'v0='+hmac.new(SECRET.encode(),b'v0:'+stamp.encode()+b':'+raw,hashlib.sha256).hexdigest()}

class Protocol(unittest.TestCase):
    def test_authenticated_unicode_message(self):
        raw=json.dumps(fixture(),ensure_ascii=False).encode()
        value=webhook.authenticated(raw,sign(raw),SECRET,NOW)
        key,event=webhook.message(value,'TTEST','ATEST')
        self.assertEqual(event['text'],'Hello 👋')
        self.assertEqual(key,'EvTEST')
    def test_signature_tamper(self):
        raw=json.dumps(fixture()).encode()
        with self.assertRaises(ValueError): webhook.authenticated(raw+b' ',sign(raw),SECRET,NOW)
    def test_stale_and_future_timestamp(self):
        for stamp in (NOW-301,NOW+301):
            with self.assertRaises(ValueError): webhook.authenticated(b'{}',sign(b'{}',stamp),SECRET,NOW)
    def test_case_insensitive_headers(self):
        raw=b'{}'
        self.assertEqual(webhook.authenticated(raw,{k.lower():v for k,v in sign(raw).items()},SECRET,NOW),{})
    def test_unsigned_challenge_rejected(self):
        with self.assertRaises(ValueError): webhook.authenticated(b'{"type":"url_verification","challenge":"a"}',{},SECRET,NOW)
    def test_signed_challenge(self):
        raw=b'{"type":"url_verification","challenge":"abc"}'
        self.assertEqual(webhook.challenge(webhook.authenticated(raw,sign(raw),SECRET,NOW)),'abc')
    def test_duplicate_keys_rejected(self):
        raw=b'{"type":"event_callback","type":"url_verification"}'
        with self.assertRaises(ValueError): webhook.authenticated(raw,sign(raw),SECRET,NOW)
    def test_wrong_workspace_and_app(self):
        for team,app in (('TOTHER','ATEST'),('TTEST','AOTHER')):
            with self.assertRaises(ValueError): webhook.message(fixture(),team,app)
    def test_non_private_and_bot_events_ignored(self):
        for data in ({'channel_type':'channel'},{'subtype':'message_changed'},{'bot_id':'BTEST'},{'files':[{}]},{'thread_ts':'x'}):
            self.assertIsNone(webhook.message(fixture(**data),'TTEST','ATEST')[1])
    def test_bad_id_and_empty_text(self):
        for data in ({'user':'http://bad'},{'channel':'CTEST'},{'text':''},{'ts':'invalid'}):
            with self.assertRaises(ValueError): webhook.message(fixture(**data),'TTEST','ATEST')
    def test_body_bound(self):
        with self.assertRaises(ValueError): webhook.authenticated(b'x'*(1024*1024+1),{},SECRET,NOW)
    def test_verify_requires_bot_identity(self):
        for data in ({'ok':True,'team_id':'TTEST','user_id':'UTEST'}, {'ok':False}):
            with patch.object(api,'call',return_value=data),self.assertRaises(ValueError): api.verify('xoxb-synthetic')
    def test_verify_identity(self):
        with patch.object(api,'call',return_value={'ok':True,'team_id':'TTEST','user_id':'UTEST','bot_id':'BTEST','team':'Demo'}):
            self.assertEqual(api.verify('xoxb-synthetic')['name'],'Demo')
    def test_test_accepted_and_unknown(self):
        for data,expected in (({'ok':True,'channel':'DTEST','ts':str(NOW)+'.000001'},'accepted'),({'ok':True,'channel':'DOTHER','ts':'x'},'unknown'),({'ok':False,'error':'missing_scope'},'failed'),({'ok':False,'error':'internal_error'},'unknown')):
            with patch.object(api,'call',return_value=data) as call:
                self.assertEqual(api.send_test('xoxb-synthetic','DTEST')[0],expected)
                self.assertEqual(call.call_count,1)
                self.assertEqual(call.call_args.args[2]['text'],api.TEST_MESSAGE)
    def test_test_timeout_never_retries(self):
        with patch.object(api,'call',side_effect=TimeoutError) as call:
            self.assertEqual(api.send_test('xoxb-synthetic','DTEST')[0],'unknown')
            self.assertEqual(call.call_count,1)
    def test_invalid_recipient_never_calls_api(self):
        with patch.object(api,'call') as call,self.assertRaises(ValueError): api.send_test('xoxb-synthetic','CTEST')
        call.assert_not_called()
    def test_vault_scope_and_encryption(self):
        bundle={'database':'test','company_id':1,'purpose_id':2,'bot_id':'BTEST','workspace_id':'TTEST','token':'xoxb-synthetic'}
        with tempfile.TemporaryDirectory() as directory:
            ref=vault.store(bundle,directory)
            scope={k:bundle[k] for k in ('database','company_id','purpose_id','bot_id','workspace_id')}
            self.assertEqual(vault.load(ref,data_dir=directory,**scope),bundle)
            for key in ('company_id','purpose_id','bot_id','workspace_id'):
                with self.assertRaises(ValueError): vault.load(ref,data_dir=directory,**(scope|{key:'wrong'}))
            for file in Path(directory).rglob('*.bin'):
                self.assertNotIn(b'xoxb-synthetic',file.read_bytes())
                self.assertEqual(file.stat().st_mode & 0o777,0o600)
            vault.remove(ref,'test',directory)
            with self.assertRaises(FileNotFoundError): vault.load(ref,data_dir=directory,**scope)
    def test_vault_reference_path_rejected(self):
        with self.assertRaises(ValueError): vault._file('../../file')
