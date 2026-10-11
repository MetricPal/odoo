"""Bounded HTTPS transport, single-tenant token acquisition and private text sends."""
import json
import re
import time
from urllib.parse import urlsplit, quote
import requests

TEST_MESSAGE = 'Teams connection test successful.'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

def valid_id(value, prefix=None):
    return isinstance(value, str) and UUID.fullmatch(value) is not None

def service_url(value):
    if not isinstance(value, str) or len(value) > 256: raise ValueError('url')
    p=urlsplit(value)
    if (p.scheme != 'https' or p.hostname != 'smba.trafficmanager.net' or p.port not in (None,443)
            or p.username or p.password or p.query or p.fragment
            or not re.fullmatch(r'/(teams|amer|emea|apac)/?',p.path)):
        raise ValueError('url')
    return value.rstrip('/')

def request_json(method, url, *, session_factory=requests.Session, **kwargs):
    # All callers choose URLs from fixed Microsoft hosts; never follow redirects.
    deadline=time.monotonic()+20
    with session_factory() as session:
        session.trust_env=False
        with getattr(session,method)(url,timeout=(5,10),verify=True,allow_redirects=False,stream=True,**kwargs) as response:
            chunks=[];size=0
            for chunk in response.iter_content(1):
                size+=len(chunk)
                if size>131072 or time.monotonic()>deadline: raise ValueError('response')
                chunks.append(chunk)
            return response.status_code,json.loads(b''.join(chunks))

def token(tenant, app, secret):
    if not valid_id(tenant) or not valid_id(app) or not isinstance(secret,str) or not 1<=len(secret)<=8192 or any(ord(c)<32 for c in secret):
        raise ValueError('credentials')
    status,data=request_json('post','https://login.microsoftonline.com/'+tenant+'/oauth2/v2.0/token',
        data={'grant_type':'client_credentials','client_id':app,'client_secret':secret,'scope':'https://api.botframework.com/.default'})
    if (status!=200 or not isinstance(data,dict) or data.get('token_type','').lower()!='bearer'
            or not isinstance(data.get('access_token'),str) or not 1<=len(data['access_token'])<=16384
            or any(c.isspace() or ord(c)<32 for c in data['access_token'])): raise ValueError('credentials')
    return data['access_token']

def send_text(credentials, route, text):
    # Complete preflight before POST; only the activity POST is an external send.
    if not isinstance(text,str) or not text.strip() or len(text)>4000 or '\x00' in text: raise ValueError('body')
    base=service_url(route['service_url'])
    conversation,member=route['thread'],route['member_id']
    if (not isinstance(conversation,str) or not 1<=len(conversation)<=256 or not conversation.startswith('a:')
            or not isinstance(member,str) or not member.startswith('29:') or len(member)>256): raise ValueError('route')
    access=token(credentials['tenant_id'],credentials['app_id'],credentials['secret'])
    activity={'type':'message','textFormat':'plain','text':text,'channelId':'msteams',
        'from':{'id':'28:'+credentials['app_id']},'recipient':{'id':member},'conversation':{'id':conversation}}
    try:
        status,data=request_json('post',base+'/v3/conversations/'+quote(conversation,safe='')+'/activities',
                                 headers={'Authorization':'Bearer '+access},json=activity)
        if status in (400,401,403,404,429) and isinstance(data,dict) and isinstance(data.get('error'),dict):
            return 'failed','rejected'
        if status in (200,201,202) and isinstance(data,dict) and isinstance(data.get('id'),str) and re.fullmatch(r'[A-Za-z0-9_.:@+/=-]{1,256}',data['id']):
            return 'accepted',data['id']
    except Exception:
        pass
    return 'unknown','unconfirmed'

def send_test(credentials, route):
    # Token failure occurs before activity I/O and is a definitive not-sent result.
    try: return send_text(credentials,route,TEST_MESSAGE)
    except Exception: return 'failed','credentials'
