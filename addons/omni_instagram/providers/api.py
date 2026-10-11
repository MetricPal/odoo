"""Instagram professional account through its linked Facebook Page token."""
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlsplit
from odoo.addons.omni_social.providers.http import call, ProviderError
VERSION='v25.0'

def node(value):
    if not isinstance(value,str) or '://' in value or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_=:$./+-]{0,299}',value): raise ValueError('identity')
    return quote(value,safe='')
def stamp(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        if result.year<2000 or result>datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=5): return None
        return result
    except (ValueError,TypeError,AttributeError): return None

def get(token,key,**params): return call('graph.facebook.com','/'+VERSION+'/'+node(key),token,params=params)[0]
def edge(token,key,edge,**params): return call('graph.facebook.com','/'+VERSION+'/'+node(key)+'/'+edge,token,params=params)[0]
def post(token,key,edge,body): return call('graph.facebook.com','/'+VERSION+'/'+node(key)+'/'+edge,token,method='POST',body=body)[0]
def result_id(result):
    try: node(result.get('id'))
    except ValueError: raise ProviderError('response',True) from None
    return result['id']

def values(result):
    data=result.get('data')
    if not isinstance(data,list) or len(data)>100: raise ValueError('response')
    return data

class Adapter:
    def verify(self,token,account='',kind='organization'):
        page=get(token,'me',fields='id,name,instagram_business_account')
        ig=page.get('instagram_business_account',{}).get('id')
        if not ig or not page.get('id'): raise ValueError('professional_page')
        node(ig); node(page['id'])
        profile=get(token,ig,fields='id,username')
        if profile.get('id')!=ig or not profile.get('username'): raise ValueError('profile')
        return {'id':ig,'page':page['id'],'name':'@'+profile['username'],'kind':'organization'}
    def validate(self,doc):
        operation=doc['operation']; limit=1000 if operation=='message' else 2200
        if not doc['body'].strip() or len(doc['body'])>limit: raise ValueError('content')
        if operation=='post' and (not doc.get('image_digest') or not doc.get('media_url')): raise ValueError('photo_required')
        if operation in ('reply','message'):
            node(doc['target']); node(doc['root'] if operation=='reply' else doc['recipient'])
        if operation not in ('post','reply','message'): raise ValueError('operation')
    def _messages(self,token,profile,thread):
        members=values(get(token,thread,fields='participants').get('participants',{}))
        own={profile['id'],profile['page']}
        if len(members)!=2 or len(own.intersection(x.get('id') for x in members))!=1: raise ValueError('private_scope')
        # Read only text. Shared posts/files are not converted into private text.
        result=[]
        for item in values(edge(token,thread,'messages',fields='id,from,to,message,created_time',limit=25)):
            sender=item.get('from',{})
            destinations=item.get('to',{}).get('data',[])
            if sender.get('id') in own or not any(d.get('id') in own for d in destinations): continue
            if sender.get('id') not in {x.get('id') for x in members} or not item.get('message') or not stamp(item.get('created_time')): continue
            result.append({'external_key':item['id'],'root_key':thread,'kind':'message','body':item['message'][:10000],
                'author':sender.get('username') or sender['id'],'recipient_key':sender['id'],'thread_key':thread,'occurred_at':stamp(item['created_time'])})
        return result
    def read(self,bundle):
        token=bundle['token']; profile=bundle['profile']; result=[]; missing=[]; started=time.monotonic()
        current=self.verify(token)
        if current['id']!=profile['id'] or current['page']!=profile['page']: raise ValueError('account')
        try:
            posts=values(edge(token,profile['id'],'media',fields='id,caption,permalink,timestamp,like_count,comments_count',limit=20))
            for media in posts:
                if time.monotonic()-started>40: missing.append('remaining activity (time limit)'); break
                node(media['id'])
                result.append({'external_key':media['id'],'kind':'post','body':media.get('caption','')[:10000],
                    'author':profile['name'],'permalink':media.get('permalink','') if urlsplit(media.get('permalink','')).scheme=='https' and urlsplit(media.get('permalink','')).hostname in ('instagram.com','www.instagram.com') else '', 'occurred_at':stamp(media.get('timestamp')),'likes':media.get('like_count',0),'comments':media.get('comments_count',0)})
                try:
                    comments=values(edge(token,media['id'],'comments',fields='id,text,username,timestamp',limit=50))
                    for comment in comments:
                        node(comment['id'])
                        result.append({'external_key':comment['id'],'root_key':media['id'],'kind':'comment','body':comment.get('text','')[:10000],
                            'author':comment.get('username',''),'occurred_at':stamp(comment.get('timestamp'))})
                except ProviderError: missing.append('comments')
        except ProviderError: missing.append('posts')
        try:
            chats=values(edge(token,profile['page'],'conversations',platform='instagram',limit=20))
            for chat in chats:
                if time.monotonic()-started>40: missing.append('remaining chats (time limit)'); break
                result.extend(self._messages(token,profile,chat['id']))
        except ProviderError: missing.append('private messages')
        note='Latest 20 posts and chats; up to 50 comments per post and 25 messages per chat.'
        if missing: note+=' Access unavailable: '+', '.join(sorted(set(missing)))+'.'
        return result,note
    def execute(self,bundle,doc,container=''):
        token=bundle['token']; profile=bundle['profile']
        try:
            self.validate(doc); current=self.verify(token)
            if current['id']!=doc['account'] or current['page']!=profile['page']: raise ValueError('account')
            if doc['operation']=='post':
                if not container:
                    created=post(token,profile['id'],'media',{'image_url':doc['media_url'],'caption':doc['body']})
                    result_id(created)
                    return 'waiting',created['id'],'Photo is processing. Publish again when ready.'
                status=get(token,container,fields='id,status_code')
                if status.get('status_code')=='IN_PROGRESS': return 'waiting',container,'Photo is still processing.'
                if status.get('status_code') in ('ERROR','EXPIRED'): return 'failed','','Photo processing failed; create a new draft.'
                if status.get('status_code')!='FINISHED': return 'unknown','','Check the container on Instagram.'
                result=post(token,profile['id'],'media_publish',{'creation_id':container})
                result_id(result); return 'sent',result['id'],'Instagram accepted the photo.'
            if doc['operation']=='reply':
                owned=get(token,doc['root'],fields='id,owner')
                if owned.get('owner',{}).get('id')!=profile['id']: raise ValueError('owner')
                if doc['target']==doc['root']:
                    result=post(token,doc['root'],'comments',{'message':doc['body']})
                else:
                    # Ensure the target is still a comment on this account's media.
                    found=values(edge(token,doc['root'],'comments',fields='id',limit=100))
                    if doc['target'] not in {x.get('id') for x in found}: raise ValueError('comment')
                    result=post(token,doc['target'],'replies',{'message':doc['body']})
                result_id(result); return 'sent',result['id'],'Instagram accepted the public reply.'
            # Fresh conversation membership and a fresh received timestamp; no unsolicited DM.
            chats=values(edge(token,profile['page'],'conversations',platform='instagram',user_id=doc['recipient'],limit=20))
            if doc['thread'] not in {x.get('id') for x in chats}: raise ValueError('thread')
            incoming=self._messages(token,profile,doc['thread'])
            if not any(x['recipient_key']==doc['recipient'] and x['occurred_at']>=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(hours=24) for x in incoming): raise ValueError('window')
            result=post(token,profile['page'],'messages',{'recipient':{'id':doc['recipient']},'message':{'text':doc['body']},'messaging_type':'RESPONSE'})
            if result.get('recipient_id')!=doc['recipient'] or not result.get('message_id'): raise ProviderError('response',True)
            return 'sent',result['message_id'],'Instagram accepted the private reply.'
        except ProviderError as error:
            return ('unknown' if error.uncertain else 'failed'),'','Check the platform before retrying.' if error.uncertain else 'Action was not sent. Check account permissions.'
        except ValueError: return 'failed','','Account, content or destination could not be verified.'
