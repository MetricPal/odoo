"""Pure transport and provider boundary checks; no API traffic."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
R=Path(__file__).resolve().parents[3]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,R/path)
    mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod); return mod
http=load('odoo.addons.omni_social.providers.http','addons/omni_social/providers/http.py')
vault=load('social_test_vault','addons/omni_social/providers/vault.py')
ig=load('social_test_ig','addons/omni_instagram/providers/api.py')
li=load('social_test_li','addons/omni_linkedin/providers/api.py')
PROFILE={'id':'urn:li:person:SELF','name':'QA','member':'urn:li:person:SELF','kind':'person'}
DOC={'account':PROFILE['id'],'operation':'post','body':'Hello','image_digest':''}
IG={'id':'100','page':'200','name':'@qa','kind':'organization'}
IGDOC={'account':'100','operation':'post','body':'Caption','image_digest':'hash','media_url':'https://social.example/image'}

class Protocol(unittest.TestCase):
    def test_fixed_host_and_method(self):
        for host,path,method in [('evil.example','/me','GET'),('graph.facebook.com','//evil.example','DELETE'),('api.linkedin.com','/posts?token=1','GET')]:
            with self.assertRaises(ValueError): http.call(host,path,'token',method=method)
    def test_token_header_injection(self):
        with self.assertRaises(ValueError): http.call('api.linkedin.com','/posts','secret\r\nInjection: 1')
    def test_transport_no_redirect_retry_proxy_and_bounded_timeout(self):
        response=Mock(status_code=200,headers={}); response.iter_content.return_value=[b'{}']
        session=Mock(); session.request.return_value=response
        with patch.object(http.requests,'Session',return_value=session): http.call('api.linkedin.com','/rest/posts','token')
        self.assertFalse(session.trust_env); self.assertEqual(session.request.call_count,1)
        kwargs=session.request.call_args.kwargs
        self.assertFalse(kwargs['allow_redirects']); self.assertTrue(kwargs['verify']); self.assertEqual(kwargs['timeout'],(5,10))
    def test_post_timeout_unknown(self):
        session=Mock(); session.request.side_effect=http.requests.Timeout('secret')
        with patch.object(http.requests,'Session',return_value=session),self.assertRaises(http.ProviderError) as error: http.call('api.linkedin.com','/rest/posts','token',method='POST')
        self.assertTrue(error.exception.uncertain); self.assertNotIn('secret',str(error.exception))
    def test_post_malformed_success_unknown(self):
        response=Mock(status_code=201,headers={}); response.iter_content.return_value=[b'not json']
        session=Mock(); session.request.return_value=response
        with patch.object(http.requests,'Session',return_value=session),self.assertRaises(http.ProviderError) as error: http.call('api.linkedin.com','/rest/posts','token',method='POST')
        self.assertTrue(error.exception.uncertain)
    def test_http_rejection_and_server_error(self):
        for code,uncertain in [(403,False),(429,False),(500,True),(302,True)]:
            response=Mock(status_code=code,headers={}); response.iter_content.return_value=[b'{}']
            session=Mock(); session.request.return_value=response
            with patch.object(http.requests,'Session',return_value=session),self.assertRaises(http.ProviderError) as error: http.call('api.linkedin.com','/rest/posts','token',method='POST')
            self.assertEqual(error.exception.uncertain,uncertain)
    def test_oversized_response(self):
        response=Mock(status_code=200,headers={}); response.iter_content.return_value=[b'x'*524289]
        session=Mock(); session.request.return_value=response
        with patch.object(http.requests,'Session',return_value=session),self.assertRaises(http.ProviderError): http.call('api.linkedin.com','/rest/posts','token')
    def test_vault_scope_and_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle={'database':'qa','company_id':1,'purpose_id':2,'provider':'instagram','account_key':'100','token':'never-plaintext'}
            ref=vault.store(bundle,directory)
            self.assertFalse(any(b'never-plaintext' in p.read_bytes() for p in Path(directory).rglob('*.bin')))
            scope={k:bundle[k] for k in ('database','company_id','purpose_id','provider','account_key')}
            self.assertEqual(vault.load(ref,data_dir=directory,**scope)['token'],bundle['token'])
            for key,bad in [('company_id',9),('purpose_id',9),('provider','linkedin'),('account_key','999')]:
                with self.assertRaises(ValueError): vault.load(ref,data_dir=directory,**(scope|{key:bad}))
    def test_linkedin_person_profile_automatic_identity(self):
        with patch.object(li,'get',return_value={'sub':'SELF','name':'QA'}): self.assertEqual(li.Adapter().verify('token',kind='person')['id'],PROFILE['id'])
    def test_linkedin_page_requires_current_role(self):
        with patch.object(li,'get',side_effect=[{'sub':'SELF'},{'elements':[]}]),self.assertRaises(ValueError): li.Adapter().verify('token','123','organization')
    def test_linkedin_post_headers_and_exact_content(self):
        with patch.object(li.Adapter,'verify',return_value=PROFILE),patch.object(li,'request',return_value=({}, {'x-restli-id':'urn:li:ugcPost:123'})) as send:
            self.assertEqual(li.Adapter().execute({'token':'token','profile':PROFILE},DOC)[0],'sent')
            args=send.call_args.args; self.assertEqual(args[1],'/rest/posts'); self.assertEqual(args[2]['commentary'],'Hello'); self.assertEqual(args[2]['author'],PROFILE['id'])
        self.assertRegex(li.HEADERS['Linkedin-Version'],r'^\d{6}$'); self.assertEqual(li.HEADERS['X-Restli-Protocol-Version'],'2.0.0')
    def test_linkedin_missing_post_id_unknown(self):
        with patch.object(li.Adapter,'verify',return_value=PROFILE),patch.object(li,'request',return_value=({}, {})):
            self.assertEqual(li.Adapter().execute({'token':'token','profile':PROFILE},DOC)[0],'unknown')
    def test_linkedin_wrong_actor_no_post(self):
        with patch.object(li.Adapter,'verify',return_value=PROFILE|{'id':'urn:li:person:OTHER'}),patch.object(li,'request') as send:
            self.assertEqual(li.Adapter().execute({'token':'token','profile':PROFILE},DOC)[0],'failed'); send.assert_not_called()
    def test_linkedin_restricted_read_reported(self):
        with patch.object(li.Adapter,'verify',return_value=PROFILE),patch.object(li,'get',side_effect=http.ProviderError('access')):
            items,note=li.Adapter().read({'token':'token','profile':PROFILE}); self.assertFalse(items); self.assertIn('approved read access',note)
    def test_linkedin_no_private_reply(self):
        with self.assertRaises(ValueError): li.Adapter().validate(DOC|{'operation':'message'})
    def test_instagram_auto_linked_profile(self):
        with patch.object(ig,'get',side_effect=[{'id':'200','instagram_business_account':{'id':'100'}},{'id':'100','username':'qa'}]): self.assertEqual(ig.Adapter().verify('token'),IG)
    def test_instagram_unlinked_page_rejected(self):
        with patch.object(ig,'get',return_value={'id':'200'}),self.assertRaises(ValueError): ig.Adapter().verify('token')
    def test_instagram_photo_required(self):
        with self.assertRaises(ValueError): ig.Adapter().validate(IGDOC|{'image_digest':''})
    def test_instagram_container_stage_one_post(self):
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'post',return_value={'id':'300'}) as send:
            result=ig.Adapter().execute({'token':'token','profile':IG},IGDOC)
            self.assertEqual(result[:2],('waiting','300')); self.assertEqual(send.call_count,1); self.assertEqual(send.call_args.args[2],'media')
    def test_instagram_staging_resume_no_new_container(self):
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'get',return_value={'id':'300','status_code':'FINISHED'}),patch.object(ig,'post',return_value={'id':'400'}) as send:
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},IGDOC,'300')[:2],('sent','400'))
            self.assertEqual(send.call_count,1); self.assertEqual(send.call_args.args[2],'media_publish')
    def test_instagram_processing_does_not_publish(self):
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'get',return_value={'status_code':'IN_PROGRESS'}),patch.object(ig,'post') as send:
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},IGDOC,'300')[0],'waiting'); send.assert_not_called()
    def test_instagram_malformed_post_response_unknown(self):
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'post',return_value={}):
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},IGDOC)[0],'unknown')
    def test_instagram_public_reply_owner_check(self):
        doc=IGDOC|{'operation':'reply','target':'501','root':'500'}
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'get',return_value={'owner':{'id':'other'}}),patch.object(ig,'post') as send:
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},doc)[0],'failed'); send.assert_not_called()
    def test_instagram_group_conversation_rejected(self):
        with patch.object(ig,'get',return_value={'participants':{'data':[{'id':'100'},{'id':'a'},{'id':'b'}]}}),self.assertRaises(ValueError): ig.Adapter()._messages('token',IG,'thread')
    def test_instagram_timestamp_guards(self):
        self.assertIsNone(ig.stamp('garbage')); self.assertIsNone(ig.stamp('2099-01-01T00:00:00Z'))
    def test_identity_path_injection(self):
        for value in ('../../me','https://evil.example','100?token=bad'):
            with self.assertRaises(ValueError): ig.node(value)
            with self.assertRaises(ValueError): li.urn(value)


class PrivateReplies(unittest.TestCase):
    def test_private_membership_and_received_text(self):
        value={'id':'mid.$123','from':{'id':'300','username':'tester'},'to':{'data':[{'id':'100'}]},'message':'Hi','created_time':ig.datetime.now(ig.timezone.utc).isoformat()}
        with patch.object(ig,'get',return_value={'participants':{'data':[{'id':'100'},{'id':'300'}]}}),patch.object(ig,'edge',return_value={'data':[value,value|{'from':{'id':'intruder'}}]}):
            result=ig.Adapter()._messages('token',IG,'thread')
            self.assertEqual(len(result),1); self.assertEqual(result[0]['recipient_key'],'300')
    def test_recent_private_reply_exact_recipient(self):
        doc=IGDOC|{'operation':'message','target':'mid.$123','root':'thread','thread':'thread','recipient':'300'}
        incoming=[{'recipient_key':'300','occurred_at':ig.datetime.now(ig.timezone.utc).replace(tzinfo=None)}]
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'edge',return_value={'data':[{'id':'thread'}]}),patch.object(ig.Adapter,'_messages',return_value=incoming),patch.object(ig,'post',return_value={'recipient_id':'300','message_id':'mid.result'}) as send:
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},doc)[0],'sent')
            self.assertEqual(send.call_args.args[1],'200'); self.assertEqual(send.call_args.args[3]['recipient'],{'id':'300'})
    def test_expired_private_window_does_not_send(self):
        doc=IGDOC|{'operation':'message','target':'mid.old','root':'thread','thread':'thread','recipient':'300'}
        incoming=[{'recipient_key':'300','occurred_at':ig.datetime.now(ig.timezone.utc).replace(tzinfo=None)-ig.timedelta(hours=25)}]
        with patch.object(ig.Adapter,'verify',return_value=IG),patch.object(ig,'edge',return_value={'data':[{'id':'thread'}]}),patch.object(ig.Adapter,'_messages',return_value=incoming),patch.object(ig,'post') as send:
            self.assertEqual(ig.Adapter().execute({'token':'token','profile':IG},doc)[0],'failed'); send.assert_not_called()
    def test_linkedin_reply_exact_actor_and_root(self):
        doc=DOC|{'operation':'reply','root':'urn:li:ugcPost:100','target':'urn:li:ugcPost:100'}
        with patch.object(li.Adapter,'verify',return_value=PROFILE),patch.object(li,'get',return_value={'author':PROFILE['id'],'visibility':'PUBLIC'}),patch.object(li,'request',return_value=({'id':'111'},{})) as send:
            self.assertEqual(li.Adapter().execute({'token':'token','profile':PROFILE},doc)[0],'sent')
            self.assertEqual(send.call_args.args[2]['object'],doc['root']); self.assertEqual(send.call_args.args[2]['actor'],PROFILE['id'])

if __name__=='__main__': unittest.main()
