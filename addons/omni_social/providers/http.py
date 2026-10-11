"""Bounded fixed-host calls; no POST retries, redirects or ambient proxies."""
import json
import time
import requests

class ProviderError(Exception):
    def __init__(self, code="provider", uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(code)

def call(host, path, token, *, method='GET', params=None, body=None, headers=None):
    if host not in ('graph.facebook.com','api.linkedin.com') or not path.startswith('/') or '?' in path or '#' in path or '\n' in path or method not in ('GET','POST'):
        raise ValueError('endpoint')
    if not isinstance(token,str) or not token or len(token)>10000 or '\n' in token or '\r' in token:
        raise ValueError('token')
    session=requests.Session(); session.trust_env=False
    response=None
    try:
        start=time.monotonic()
        response=session.request(method,'https://'+host+path, params=params, json=body,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',**(headers or {})},
            timeout=(5,10),allow_redirects=False,stream=True,verify=True)
        raw=bytearray()
        for chunk in response.iter_content(8192):
            raw.extend(chunk)
            if len(raw)>524288 or time.monotonic()-start>20: raise ProviderError('response',method=='POST')
        if not 200 <= response.status_code < 300:
            # Do not infer non-execution from server errors or redirects.
            safe = response.status_code in (400,401,403,404,422,429)
            raise ProviderError('access' if response.status_code in (401,403) else 'rejected',method=='POST' and not safe)
        value=json.loads(raw) if raw else {}
        if not isinstance(value,dict): raise ProviderError('response',method=='POST')
        return value,dict(response.headers)
    except (requests.RequestException,ValueError) as error:
        raise ProviderError('network',method=='POST') from error
    finally:
        if response is not None: response.close()
        session.close()
