"""Versioned LinkedIn REST: Pages and profiles, with restricted reads explicit."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote
from odoo.addons.omni_social.providers.http import call, upload_linkedin, ProviderError
VERSION='202609'
HEADERS={'Linkedin-Version':VERSION,'X-Restli-Protocol-Version':'2.0.0'}

def urn(value,kind='actor'):
    patterns={'actor':r'urn:li:(?:organization:[0-9]+|person:[A-Za-z0-9_-]+)',
        'post':r'urn:li:(?:share|ugcPost):[0-9]+','comment':r'urn:li:comment:\(urn:li:(?:share|ugcPost|activity):[0-9]+,[0-9]+\)'}
    if not isinstance(value,str) or not re.fullmatch(patterns[kind],value): raise ValueError('identity')
    return quote(value,safe='')
def get(token,path,**params): return call('api.linkedin.com',path,token,params=params,headers={**HEADERS,**({'X-Restli-Method':'FINDER'} if params.get('q') else {})})[0]
def request(token,path,body): return call('api.linkedin.com',path,token,method='POST',body=body,headers=HEADERS)
def elements(result):
    items=result.get('elements')
    if not isinstance(items,list) or len(items)>100: raise ValueError('response')
    return items

def date(ms):
    if not isinstance(ms,(int,float)) or isinstance(ms,bool): return None
    try: return datetime.fromtimestamp(ms/1000,timezone.utc).replace(tzinfo=None)
    except (ValueError,OverflowError,OSError): return None

class Adapter:
    def verify(self,token,account='',kind='organization'):
        member=get(token,'/v2/userinfo')
        subject=member.get('sub')
        if not subject or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',subject): raise ValueError('member')
        person='urn:li:person:'+subject
        if kind=='person': return {'id':person,'name':member.get('name') or person,'member':person,'kind':'person'}
        if not re.fullmatch(r'[0-9]{1,30}',account): raise ValueError('page')
        actor='urn:li:organization:'+account
        roles=elements(get(token,'/rest/organizationAcls',q='roleAssignee',state='APPROVED',count=100))
        if not any(r.get('organizationalTarget')==actor and r.get('roleAssignee')==person and r.get('role') in ('ADMINISTRATOR','CONTENT_ADMIN','CONTENT_ADMINISTRATOR') for r in roles): raise ValueError('role')
        info=get(token,'/rest/organizations/'+account)
        if str(info.get('id'))!=account: raise ValueError('page')
        return {'id':actor,'name':info.get('localizedName') or actor,'member':person,'kind':'organization'}
    def validate(self,doc):
        urn(doc['account'])
        if not doc['body'].strip() or len(doc['body'])>3000: raise ValueError('content')
        if doc['operation'] not in ('post','reply') or doc.get('image_digest') or doc.get('format','standard') not in ('standard','carousel'): raise ValueError('operation')
        media=doc.get('media',[])
        if media and (doc['operation']!='post' or any(m['kind']!='image' for m in media) or not 1<=len(media)<=20 or (doc.get('format')=='carousel' and len(media)<2)): raise ValueError('media')
        if doc.get('format')=='carousel' and not media: raise ValueError('media')
        if doc['operation']=='reply':
            urn(doc['root'],'post')
            if doc['target']!=doc['root']: urn(doc['target'],'comment')
    def read(self,bundle):
        token=bundle['token']; profile=bundle['profile']; actor=profile['id']; items=[]; missing=[]; started=time.monotonic()
        account=actor.rsplit(':',1)[-1] if profile['kind']=='organization' else ''
        if self.verify(token,account,profile['kind'])['id']!=actor: raise ValueError('account')
        try:
            posts=elements(get(token,'/rest/posts',q='author',author=actor,count=20,sortBy='LAST_MODIFIED'))
            for item in posts:
                if time.monotonic()-started>40: missing.append('remaining activity (time limit)'); break
                if item.get('author')!=actor: raise ValueError('author')
                if item.get('visibility')!='PUBLIC' or item.get('lifecycleState')!='PUBLISHED': continue
                key=item['id']; urn(key,'post')
                vals={'external_key':key,'kind':'post','body':item.get('commentary','')[:10000],'author':profile['name'],'permalink':'https://www.linkedin.com/feed/update/'+quote(key,safe=':'), 'occurred_at':date(item.get('publishedAt'))}
                try:
                    summary=get(token,'/rest/socialActions/'+urn(key,'post'))
                    vals.update(likes=summary.get('likesSummary',{}).get('aggregatedTotalLikes',0),comments=summary.get('commentsSummary',{}).get('aggregatedTotalComments',0))
                    for comment in elements(get(token,'/rest/socialActions/'+urn(key,'post')+'/comments',count=50)):
                        target=comment.get('commentUrn'); urn(target,'comment')
                        items.append({'external_key':target,'root_key':key,'kind':'comment','body':comment.get('message',{}).get('text','')[:10000],
                            'author':comment.get('actor',''),'occurred_at':date(comment.get('created',{}).get('time'))})
                except ProviderError: missing.append('comments and engagement')
                items.append(vals)
        except ProviderError: missing.append('posts (approved read access required)')
        note='Latest 20 posts; up to 50 comments per post.'
        if missing: note+=' Access unavailable: '+', '.join(sorted(set(missing)))+'.'
        return items,note
    def execute(self,bundle,doc,container=''):
        token=bundle['token']; profile=bundle['profile']; attempted=False
        try:
            self.validate(doc)
            account=profile['id'].rsplit(':',1)[-1] if profile['kind']=='organization' else ''
            current=self.verify(token,account,profile['kind'])
            if current['id']!=doc['account'] or current['member']!=profile['member']: raise ValueError('actor')
            if doc['operation']=='post':
                body={'author':doc['account'],'commentary':doc['body'],'visibility':'PUBLIC',
                    'distribution':{'feedDistribution':'MAIN_FEED','targetEntities':[],'thirdPartyDistributionChannels':[]},
                    'lifecycleState':'PUBLISHED','isReshareDisabledByAuthor':False}
                if doc.get('media'):
                    stage=json.loads(container) if container else {'images':[]}
                    images=stage['images']; media=doc['media']
                    if len(images)<len(media) and (not images or images[-1].get('uploaded')):
                        attempted=True
                        value,_=call('api.linkedin.com','/rest/images',token,method='POST',params={'action':'initializeUpload'},body={'initializeUploadRequest':{'owner':doc['account']}},headers=HEADERS)
                        item=value.get('value',{})
                        if not re.fullmatch(r'urn:li:image:[A-Za-z0-9_-]+',item.get('image','')) or not item.get('uploadUrl'): raise ValueError('image')
                        images.append({'id':item['image'],'url':item['uploadUrl'],'uploaded':False})
                        return 'waiting',json.dumps(stage),'Preparing media.'
                    if not images[-1]['uploaded']:
                        item=media[len(images)-1]; attempted=True
                        upload_linkedin(images[-1]['url'],token,bundle['media_bytes'][item['id']])
                        images[-1]['uploaded']=True
                        return 'waiting',json.dumps(stage),'Preparing media.'
                    for image in images:
                        status=get(token,'/rest/images/'+quote(image['id'],safe=''))
                        if status.get('owner')!=doc['account'] or status.get('id')!=image['id']: raise ValueError('image_owner')
                        if status.get('status') in ('WAITING_UPLOAD','PROCESSING'): return 'waiting',json.dumps(stage),'Media is processing. Continue when ready.'
                        if status.get('status')!='AVAILABLE': raise ValueError('image_status')
                    ordered=[{'id':image['id'],'altText':item['alt_text']} for image,item in zip(images,media)]
                    body['content']={'multiImage':{'images':ordered}} if len(ordered)>1 else {'media':ordered[0]}
                attempted=True; value,headers=request(token,'/rest/posts',body)
                key=next((v for k,v in headers.items() if k.lower()=='x-restli-id'),None)
                urn(key,'post')
                return 'sent',key,'LinkedIn accepted the post.'
            owned=get(token,'/rest/posts/'+urn(doc['root'],'post'))
            if owned.get('author')!=doc['account'] or owned.get('visibility')!='PUBLIC': raise ValueError('owner')
            body={'actor':doc['account'],'object':doc['root'],'message':{'text':doc['body']}}
            if doc['target']!=doc['root']:
                comments=elements(get(token,'/rest/socialActions/'+urn(doc['root'],'post')+'/comments',count=100))
                if doc['target'] not in {x.get('commentUrn') for x in comments}: raise ValueError('comment')
                body['parentComment']=doc['target']
            attempted=True
            value,headers=request(token,'/rest/socialActions/'+urn(doc['root'],'post')+'/comments',body)
            if not value.get('id'): raise ValueError('response')
            return 'sent',str(value['id']),'LinkedIn accepted the public reply.'
        except ProviderError as error:
            return ('unknown' if error.uncertain else 'failed'),'','Check LinkedIn before retrying.' if error.uncertain else 'Action was not sent. Check account permissions.'
        except ValueError:
            return ('unknown' if attempted else 'failed'),'','Check LinkedIn before retrying.' if attempted else 'Account, content or destination could not be verified.'
