"""Threads API for one profile (graph.threads.net).

Publishing is two-step on Threads: create a media container, then publish it.
Each step is its own committed claim, so an interrupted publish resumes from
the saved container instead of creating a second post. Videos and carousels
wait until Threads reports the container as finished.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call

HOST = 'graph.threads.net'
VERSION = 'v1.0'
TEXT_LIMIT = 500


def node(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,40}', value):
        raise ValueError('identity')
    return quote(value, safe='')


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00').replace('+0000', '+00:00'))
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 2000 or result > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
        return None


def get(token, key, name='', **params):
    path = '/' + VERSION + '/' + ('me' if key == 'me' else node(key)) + ('/' + name if name else '')
    return call(HOST, path, token, params=params)[0]


def post(token, key, name, body):
    return call(HOST, '/' + VERSION + '/' + node(key) + '/' + name, token, method='POST', body=body)[0]


def result_id(result):
    try:
        node(result.get('id'))
    except ValueError:
        raise ProviderError('response', True) from None
    return result['id']


def values(result):
    data = result.get('data')
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError('response')
    return data


def permalink(url):
    parts = urlsplit(url or '')
    return url if parts.scheme == 'https' and parts.hostname in ('threads.net', 'www.threads.net', 'threads.com',
                                                                 'www.threads.com') else ''


class Adapter:
    CAPABILITIES = Capabilities(
        label='Threads',
        hosts=(HOST,),
        operations=('post', 'reply'),
        formats=('standard', 'carousel'),
        text_limit=TEXT_LIMIT,
        media_kinds=('image', 'video'),
        max_media=20,
        format_media={'standard': (0, 1, ('image', 'video')), 'carousel': (2, 20, ('image', 'video'))},
        needs_public_url=True,
        daily_limits={'post': 250, 'reply': 1000},
        oauth=OAuth(
            authorize_url='https://threads.net/oauth/authorize',
            token_url='https://graph.threads.net/oauth/access_token',
            scopes=('threads_basic', 'threads_content_publish', 'threads_read_replies', 'threads_manage_replies'),
            scope_separator=',',
        ),
        token_hint='Use a long-lived Threads user access token with threads_content_publish.',
        developer_url='https://developers.facebook.com/apps/',
    )

    def verify(self, token, account='', kind='organization'):
        me = get(token, 'me', fields='id,username')
        node(me.get('id'))
        if not isinstance(me.get('username'), str) or not me['username']:
            raise ValueError('profile')
        return {'id': me['id'], 'name': '@' + me['username'], 'username': me['username'], 'kind': 'organization'}

    def oauth_token(self, response, app, account=''):
        """Exchange the one-hour token for a 60-day token; it is renewed before it lapses."""
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        long_lived = call(HOST, '/access_token', token,
                          params={'grant_type': 'th_exchange_token', 'client_secret': app['client_secret']})[0]
        token = long_lived.get('access_token') or token
        seconds = long_lived.get('expires_in')
        details = {}
        if isinstance(seconds, (int, float)):
            details['expires_at'] = (datetime.now(timezone.utc).replace(tzinfo=None)
                                     + timedelta(seconds=int(seconds))).isoformat()
        return token, details

    def oauth_refresh(self, bundle):
        return call(HOST, '/refresh_access_token', bundle['token'], params={'grant_type': 'th_refresh_token'})[0]

    def validate(self, doc):
        operation, body = doc['operation'], doc['body']
        if len(body) > TEXT_LIMIT:
            raise ValueError('content')
        if operation == 'post':
            media = doc.get('media', [])
            fmt = doc.get('format', 'standard')
            if not body.strip() and not media:
                raise ValueError('content')
            if fmt == 'carousel' and not 2 <= len(media) <= 20:
                raise ValueError('count')
            if fmt == 'standard' and len(media) > 1:
                raise ValueError('count')
            if fmt not in ('standard', 'carousel'):
                raise ValueError('format')
            for item in media:
                if urlsplit(item.get('url', '')).scheme != 'https':
                    raise ValueError('media_url')
        elif operation == 'reply':
            if not body.strip():
                raise ValueError('content')
            node(doc['target'])
            node(doc['root'])
        else:
            raise ValueError('operation')

    def read(self, bundle):
        token, profile = bundle['token'], bundle['profile']
        if self.verify(token)['id'] != profile['id']:
            raise ValueError('account')
        result, missing = [], []
        started = time.monotonic()
        try:
            posts = values(get(token, profile['id'], 'threads', limit=20,
                               fields='id,text,permalink,timestamp,media_type,is_reply'))
        except ProviderError:
            return [], 'Access unavailable: posts.'
        for item in posts:
            if item.get('is_reply'):
                continue
            if time.monotonic() - started > 40:
                missing.append('remaining posts (time limit)')
                break
            node(item['id'])
            likes = replies = 0
            try:
                for metric in values(get(token, item['id'], 'insights', metric='likes,replies')):
                    value = ((metric.get('values') or [{}])[0]).get('value', 0)
                    if metric.get('name') == 'likes':
                        likes = value if isinstance(value, int) else 0
                    elif metric.get('name') == 'replies':
                        replies = value if isinstance(value, int) else 0
            except (ProviderError, ValueError):
                missing.append('engagement counts')
            result.append({
                'external_key': item['id'], 'kind': 'post', 'body': (item.get('text') or '')[:10000],
                'author': profile['name'], 'permalink': permalink(item.get('permalink')),
                'occurred_at': stamp(item.get('timestamp')), 'likes': likes, 'comments': replies,
                'format': item.get('media_type', ''),
            })
            try:
                for reply in values(get(token, item['id'], 'replies', fields='id,text,username,timestamp')):
                    if reply.get('username') == profile.get('username') or not reply.get('text'):
                        continue
                    node(reply['id'])
                    result.append({
                        'external_key': reply['id'], 'root_key': item['id'], 'kind': 'comment',
                        'body': reply['text'][:10000], 'author': '@' + (reply.get('username') or ''),
                        'occurred_at': stamp(reply.get('timestamp')),
                    })
            except ProviderError:
                missing.append('replies')
        note = 'Latest 20 Threads posts with their replies.'
        if missing:
            note += ' Access unavailable: ' + ', '.join(sorted(set(missing))) + '.'
        return result, note

    def _container(self, doc):
        media = doc.get('media', [])
        body = {'text': doc['body']} if doc['body'] else {}
        if doc['operation'] == 'reply':
            return {'media_type': 'TEXT', 'reply_to_id': doc['target'], **body}
        if not media:
            return {'media_type': 'TEXT', **body}
        item = media[0]
        key = 'image_url' if item['kind'] == 'image' else 'video_url'
        return {'media_type': 'IMAGE' if item['kind'] == 'image' else 'VIDEO', key: item['url'], **body}

    def _status(self, token, container):
        return get(token, container, fields='id,status').get('status')

    def execute(self, bundle, doc, container=''):
        token, profile = bundle['token'], bundle['profile']
        try:
            self.validate(doc)
            if self.verify(token)['id'] != doc['account']:
                raise ValueError('account')
            user = profile['id']
            if doc['operation'] == 'reply':
                owner = get(token, doc['root'], fields='id,username')
                if owner.get('username') != profile.get('username'):
                    raise ValueError('owner')
            stage = json.loads(container) if container else {'children': [], 'parent': ''}
            media = doc.get('media', [])
            if doc.get('format') == 'carousel' and doc['operation'] == 'post':
                if len(stage['children']) < len(media):
                    item = media[len(stage['children'])]
                    key = 'image_url' if item['kind'] == 'image' else 'video_url'
                    created = post(token, user, 'threads', {
                        'media_type': 'IMAGE' if item['kind'] == 'image' else 'VIDEO', key: item['url'],
                        'is_carousel_item': True,
                    })
                    stage['children'].append(result_id(created))
                    return 'waiting', json.dumps(stage), 'Preparing media.'
                if not stage['parent']:
                    for child in stage['children']:
                        status = self._status(token, child)
                        if status == 'IN_PROGRESS':
                            return 'waiting', json.dumps(stage), 'Media is processing. Continue when ready.'
                        if status != 'FINISHED':
                            return 'failed', '', 'A carousel item failed to process.'
                    created = post(token, user, 'threads', {
                        'media_type': 'CAROUSEL', 'children': ','.join(stage['children']),
                        **({'text': doc['body']} if doc['body'] else {}),
                    })
                    stage['parent'] = result_id(created)
                    return 'waiting', json.dumps(stage), 'Preparing media.'
            elif not stage['parent']:
                stage['parent'] = result_id(post(token, user, 'threads', self._container(doc)))
                return 'waiting', json.dumps(stage), 'Preparing media.'
            status = self._status(token, stage['parent'])
            if status == 'IN_PROGRESS':
                return 'waiting', json.dumps(stage), 'Media is processing. Continue when ready.'
            if status in ('ERROR', 'EXPIRED'):
                return 'failed', '', 'Threads could not process this post.'
            if status not in ('FINISHED', None):
                return 'unknown', '', 'Check Threads before taking further action.'
            published = post(token, user, 'threads_publish', {'creation_id': stage['parent']})
            return 'sent', result_id(published), 'Threads accepted the post.'
        except ProviderError as error:
            return (('unknown' if error.uncertain else 'failed'), '',
                    'Check the platform before retrying.' if error.uncertain
                    else 'Action was not sent. Check the profile permissions.')
        except ValueError:
            return 'failed', '', 'Profile, content or destination could not be verified.'
