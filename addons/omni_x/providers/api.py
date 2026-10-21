"""X API v2 for one account, pay-per-use.

Prices are the pay-per-use rates published in 2026 (see the README); they
live here so a price change touches one file. Each publish and each sync is
priced before the call and recorded by Social's usage meter.
"""

import re
import time
from datetime import datetime, timedelta, timezone

import requests

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call

HOST = 'api.x.com'
TEXT_LIMIT = 280
POST_PRICE = 0.015       # per post created
LINK_POST_PRICE = 0.20   # per post created that contains a link
READ_PRICE = 0.005       # per post read
READ_BATCH = 10          # posts read per list call (timeline, mentions)
URL = re.compile(r'https?://\S+|\b[\w-]+\.(?:com|net|org|io|co|ai|app|dev)\b/?\S*', re.I)


def post_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,25}', value):
        raise ValueError('identity')
    return value


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 2006 or result > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
        return None


def get(token, path, **params):
    return call(HOST, '/2/' + path, token, params=params)[0]


def upload_image(token, raw, mime):
    """Simple media upload (multipart); the image is not visible until a post uses it."""
    if not 0 < len(raw) <= 5 * 1024 * 1024 or mime not in ('image/jpeg', 'image/png'):
        raise ValueError('media')
    if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
        raise ValueError('token')
    session = requests.Session()
    session.trust_env = False
    response = None
    try:
        response = session.post('https://%s/2/media/upload' % HOST, files={'media': ('image', raw, mime)},
                                data={'media_category': 'tweet_image'}, headers={'Authorization': 'Bearer ' + token},
                                timeout=(5, 60), allow_redirects=False, verify=True)
        if response.status_code not in (200, 201):
            raise ProviderError('rejected')
        value = response.json()
        key = ((value.get('data') or {}).get('id')) if isinstance(value, dict) else None
        return post_id(key)
    except requests.RequestException:
        raise ProviderError('network') from None
    except ValueError:
        raise ProviderError('response') from None
    finally:
        if response is not None:
            response.close()
        session.close()


class Adapter:
    CAPABILITIES = Capabilities(
        label='X',
        hosts=(HOST,),
        operations=('post', 'reply'),
        formats=('standard', 'carousel'),
        text_limit=TEXT_LIMIT,
        media_kinds=('image',),
        max_media=4,
        upload_bytes=True,
        costs={'post': POST_PRICE, 'reply': POST_PRICE, 'read': READ_PRICE * READ_BATCH * 2},
        oauth=OAuth(
            authorize_url='https://x.com/i/oauth2/authorize',
            token_url='https://api.x.com/2/oauth2/token',
            scopes=('tweet.read', 'tweet.write', 'users.read', 'media.write', 'offline.access'),
            pkce=True,
            client_auth='basic',
        ),
        token_hint='Sign in with X instead: access tokens expire after two hours.',
        developer_url='https://developer.x.com/en/portal/dashboard',
    )

    def verify(self, token, account='', kind='organization'):
        me = (get(token, 'users/me').get('data') or {})
        key = post_id(me.get('id'))
        username = me.get('username')
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}', username):
            raise ValueError('profile')
        return {'id': key, 'name': '@' + username, 'username': username, 'kind': 'organization'}

    def oauth_token(self, response, app, account=''):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        return token, {}

    def cost(self, operation, doc):
        """Posts with a link cost more on pay-per-use."""
        if operation not in ('post', 'reply'):
            return 0.0
        return LINK_POST_PRICE if URL.search(doc.get('body') or '') else POST_PRICE

    def read_cost(self):
        return READ_PRICE * READ_BATCH * 2

    def validate(self, doc):
        operation, body = doc['operation'], doc['body']
        media = doc.get('media', [])
        if len(body) > TEXT_LIMIT or (not body.strip() and not media):
            raise ValueError('content')
        if operation == 'post':
            if len(media) > 4 or any(m['kind'] != 'image' for m in media):
                raise ValueError('media')
        elif operation == 'reply':
            post_id(doc['target'])
            post_id(doc['root'])
            if media:
                raise ValueError('media')
        else:
            raise ValueError('operation')

    def read(self, bundle):
        token, profile = bundle['token'], bundle['profile']
        if self.verify(token)['id'] != profile['id']:
            raise ValueError('account')
        result, missing = [], []
        started = time.monotonic()
        try:
            posts = get(token, 'users/%s/tweets' % profile['id'], max_results=READ_BATCH,
                        exclude='replies,retweets', **{'tweet.fields': 'created_at,public_metrics'}).get('data') or []
            for item in posts[:READ_BATCH]:
                metrics = item.get('public_metrics') or {}
                result.append({
                    'external_key': post_id(item.get('id')), 'kind': 'post', 'body': (item.get('text') or '')[:10000],
                    'author': profile['name'], 'occurred_at': stamp(item.get('created_at')),
                    'permalink': 'https://x.com/%s/status/%s' % (profile['username'], item['id']),
                    'likes': int(metrics.get('like_count', 0) or 0), 'comments': int(metrics.get('reply_count', 0) or 0),
                })
        except ProviderError:
            missing.append('posts')
        if time.monotonic() - started < 40:
            try:
                answer = get(token, 'users/%s/mentions' % profile['id'], max_results=READ_BATCH, expansions='author_id',
                             **{'tweet.fields': 'created_at,conversation_id,author_id', 'user.fields': 'username'})
                names = {u.get('id'): u.get('username') for u in (answer.get('includes') or {}).get('users') or []}
                for item in (answer.get('data') or [])[:READ_BATCH]:
                    if item.get('author_id') == profile['id']:
                        continue
                    result.append({
                        'external_key': post_id(item.get('id')), 'kind': 'comment',
                        'root_key': post_id(item.get('conversation_id') or item['id']),
                        'body': (item.get('text') or '')[:10000],
                        'author': '@' + (names.get(item.get('author_id')) or ''),
                        'occurred_at': stamp(item.get('created_at')),
                    })
            except ProviderError:
                missing.append('mentions')
        note = 'Latest %s posts and %s mentions (each read is charged by X).' % (READ_BATCH, READ_BATCH)
        if missing:
            note += ' Access unavailable: ' + ', '.join(missing) + '.'
        return result, note

    def execute(self, bundle, doc, container=''):
        token, profile = bundle['token'], bundle['profile']
        try:
            self.validate(doc)
            if self.verify(token)['id'] != doc['account'] or doc['account'] != profile['id']:
                raise ValueError('account')
            body = {'text': doc['body']}
            if doc['operation'] == 'reply':
                body['reply'] = {'in_reply_to_tweet_id': doc['target']}
            media = doc.get('media', [])
            if media:
                # Uploaded images stay invisible until the post uses them, so uploading is safe to repeat.
                ids = [upload_image(token, bundle['media_bytes'][m['id']], m['mime']) for m in media]
                body['media'] = {'media_ids': ids}
            created = call(HOST, '/2/tweets', token, method='POST', body=body)[0]
            try:
                key = post_id((created.get('data') or {}).get('id'))
            except ValueError:
                raise ProviderError('response', True) from None  # the post may exist
            return 'sent', key, 'X accepted the post.'
        except ProviderError as error:
            return (('unknown' if error.uncertain else 'failed'), '',
                    'Check X before retrying.' if error.uncertain
                    else 'The post was not sent. Check the account permissions.')
        except (ValueError, KeyError):
            return 'failed', '', 'Account, content or destination could not be verified.'
