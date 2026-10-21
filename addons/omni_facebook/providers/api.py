"""Facebook Page through a Page access token (Graph API).

Reads the Page's latest posts and their comments; publishes text, photo,
multi-photo and video posts and public replies. Messenger is not handled
here: private chats belong to Omnichannel.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call, call_form

VERSION = 'v25.0'
TEXT_LIMIT = 63206
REPLY_LIMIT = 8000


def node(value):
    if (
        not isinstance(value, str)
        or '://' in value
        or not re.fullmatch(r'[0-9]{1,40}(?:_[0-9]{1,40})?', value)
    ):
        raise ValueError('identity')
    return quote(value, safe='')


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 2000 or result > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
        return None


def get(token, key, **params):
    path = '/' + VERSION + '/' + ('me' if key == 'me' else node(key))
    return call('graph.facebook.com', path, token, params=params)[0]


def edge(token, key, name, **params):
    path = '/' + VERSION + '/' + ('me' if key == 'me' else node(key)) + '/' + name
    return call('graph.facebook.com', path, token, params=params)[0]


def post(token, key, name, body):
    return call('graph.facebook.com', '/' + VERSION + '/' + node(key) + '/' + name, token, method='POST', body=body)[0]


def result_id(result, field='id'):
    try:
        node(result.get(field))
    except ValueError:
        raise ProviderError('response', True) from None
    return result[field]


def values(result):
    data = result.get('data')
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError('response')
    return data


def permalink(url):
    parts = urlsplit(url or '')
    return url if parts.scheme == 'https' and parts.hostname in ('facebook.com', 'www.facebook.com') else ''


class Adapter:
    CAPABILITIES = Capabilities(
        label='Facebook',
        hosts=('graph.facebook.com',),
        operations=('post', 'reply'),
        formats=('standard', 'carousel'),
        text_limit=TEXT_LIMIT,
        media_kinds=('image', 'video'),
        max_media=10,
        needs_public_url=True,
        oauth=OAuth(
            authorize_url='https://www.facebook.com/' + VERSION + '/dialog/oauth',
            token_url='https://graph.facebook.com/' + VERSION + '/oauth/access_token',
            scopes=(
                'pages_show_list',
                'pages_read_engagement',
                'pages_read_user_content',
                'pages_manage_posts',
                'pages_manage_engagement',
            ),
            scope_separator=',',
        ),
        token_hint='Use a Page access token (not a user token) for the Page you publish to.',
        developer_url='https://developers.facebook.com/apps/',
        account_label='Facebook Page ID (only if you manage several Pages)',
    )

    def verify(self, token, account='', kind='organization'):
        page = get(token, 'me', fields='id,name,category')
        # Only Page tokens describe a Page (they carry a category); user tokens are refused.
        if not page.get('id') or not page.get('name') or not page.get('category'):
            raise ValueError('page_token')
        node(page['id'])
        if account and page['id'] != account:
            raise ValueError('page')
        return {'id': page['id'], 'page': page['id'], 'name': page['name'], 'kind': 'organization'}

    def oauth_token(self, response, app, account=''):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        long_lived = call_form(
            self.CAPABILITIES.oauth.token_url,
            {
                'grant_type': 'fb_exchange_token',
                'client_id': app['client_id'],
                'client_secret': app['client_secret'],
                'fb_exchange_token': token,
            },
        ).get('access_token') or token
        pages = values(edge(long_lived, 'me', 'accounts', fields='id,name,access_token', limit=100))
        chosen = [p for p in pages if p.get('access_token') and (not account or p.get('id') == account)]
        if len(chosen) != 1:
            raise ValueError('page_choice')
        return chosen[0]['access_token'], {}

    def validate(self, doc):
        operation = doc['operation']
        body = doc['body']
        if operation == 'post':
            media = doc.get('media', [])
            fmt = doc.get('format', 'standard')
            if (not body.strip() and not media) or len(body) > TEXT_LIMIT:
                raise ValueError('content')
            if fmt == 'carousel':
                if not 2 <= len(media) <= 10 or any(item['kind'] != 'image' for item in media):
                    raise ValueError('count')
            elif fmt == 'standard':
                if len(media) > 1:
                    raise ValueError('count')
            else:
                raise ValueError('format')
            for item in media:
                parts = urlsplit(item.get('url', ''))
                if parts.scheme != 'https' or not parts.hostname:
                    raise ValueError('media_url')
        elif operation == 'reply':
            if not body.strip() or len(body) > REPLY_LIMIT:
                raise ValueError('content')
            node(doc['target'])
            node(doc['root'])
        else:
            raise ValueError('operation')

    def read(self, bundle):
        token = bundle['token']
        profile = bundle['profile']
        current = self.verify(token)
        if current['id'] != profile['id']:
            raise ValueError('account')
        page = profile['id']
        result, missing = [], []
        started = time.monotonic()
        try:
            posts = values(edge(
                token, page, 'posts', limit=20,
                fields='id,message,permalink_url,created_time,'
                       'reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)',
            ))
        except ProviderError:
            return [], 'Access unavailable: posts.'
        for item in posts:
            if time.monotonic() - started > 40:
                missing.append('remaining posts (time limit)')
                break
            node(item['id'])
            result.append({
                'external_key': item['id'],
                'kind': 'post',
                'body': (item.get('message') or '')[:10000],
                'author': profile['name'],
                'permalink': permalink(item.get('permalink_url')),
                'occurred_at': stamp(item.get('created_time')),
                'likes': ((item.get('reactions') or {}).get('summary') or {}).get('total_count', 0),
                'comments': ((item.get('comments') or {}).get('summary') or {}).get('total_count', 0),
            })
            try:
                comments = values(edge(token, item['id'], 'comments', fields='id,message,from,created_time',
                                       filter='stream', limit=50))
            except ProviderError:
                missing.append('comments')
                continue
            for comment in comments:
                author = comment.get('from') or {}
                if author.get('id') == page or not comment.get('message'):
                    continue  # Our own replies are not something to answer.
                node(comment['id'])
                result.append({
                    'external_key': comment['id'],
                    'root_key': item['id'],
                    'kind': 'comment',
                    'body': comment['message'][:10000],
                    'author': author.get('name', ''),
                    'occurred_at': stamp(comment.get('created_time')),
                })
        note = 'Latest 20 Page posts; up to 50 comments per post.'
        if missing:
            note += ' Access unavailable: ' + ', '.join(sorted(set(missing))) + '.'
        return result, note

    def _carousel(self, token, page, doc, container):
        # One mutation per committed claim: each unpublished photo, then the post.
        stage = json.loads(container) if container else {'photos': []}
        media = doc['media']
        if len(stage['photos']) < len(media):
            item = media[len(stage['photos'])]
            created = post(token, page, 'photos', {'url': item['url'], 'published': False,
                                                  'alt_text_custom': item.get('alt_text', '')})
            stage['photos'].append(result_id(created))
            return 'waiting', json.dumps(stage), 'Preparing media.'
        created = post(token, page, 'feed', {
            'message': doc['body'],
            'attached_media': [{'media_fbid': photo} for photo in stage['photos']],
        })
        return 'sent', result_id(created), 'Facebook accepted the post.'

    def execute(self, bundle, doc, container=''):
        token = bundle['token']
        profile = bundle['profile']
        try:
            self.validate(doc)
            current = self.verify(token)
            if current['id'] != doc['account'] or current['id'] != profile['id']:
                raise ValueError('account')
            page = profile['id']
            if doc['operation'] == 'post':
                media = doc.get('media', [])
                if doc.get('format') == 'carousel':
                    return self._carousel(token, page, doc, container)
                if not media:
                    created = post(token, page, 'feed', {'message': doc['body']})
                    return 'sent', result_id(created), 'Facebook accepted the post.'
                item = media[0]
                if item['kind'] == 'image':
                    created = post(token, page, 'photos', {'url': item['url'], 'caption': doc['body']})
                    key = created.get('post_id') or created.get('id')
                    return 'sent', result_id({'id': key}), 'Facebook accepted the photo.'
                created = post(token, page, 'videos', {'file_url': item['url'], 'description': doc['body']})
                return 'sent', result_id(created), 'Facebook accepted the video; it can take a few minutes to appear.'
            # Public reply: the post must belong to this Page.
            owner = get(token, doc['root'], fields='id,from')
            if (owner.get('from') or {}).get('id') != page:
                raise ValueError('owner')
            created = post(token, doc['target'], 'comments', {'message': doc['body']})
            return 'sent', result_id(created), 'Facebook accepted the reply.'
        except ProviderError as error:
            return (
                ('unknown' if error.uncertain else 'failed'),
                '',
                'Check the platform before retrying.' if error.uncertain
                else 'Action was not sent. Check the Page permissions.',
            )
        except ValueError:
            return 'failed', '', 'Page, content or destination could not be verified.'
