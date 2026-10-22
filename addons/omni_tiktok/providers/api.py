"""TikTok Content Posting API (direct post) for one creator account.

Video: open the post (FILE_UPLOAD), send the file, then follow TikTok's
processing status. Photo posts: TikTok pulls the images from the account's
public address (that domain must be verified in the TikTok app). Each step is
a committed claim; a lost upload or a lost photo request is "check the
platform", never repeated.
"""

import json
import re
from urllib.parse import urlsplit

import requests

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call

HOST = 'open.tiktokapis.com'
UPLOAD_HOST = 'open-upload.tiktokapis.com'
CAPTION_LIMIT = 2200
PHOTO_TITLE_LIMIT = 90
MAX_PHOTOS = 35
PREFERRED_PRIVACY = ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')


def api(token, path, body=None):
    """TikTok answers {'data': ..., 'error': {'code': 'ok'}}; anything else is a failure."""
    value = call(HOST, '/v2/' + path, token, method='POST' if body is not None else 'GET',
                 params={'fields': 'open_id,display_name,username'} if path == 'user/info/' else None,
                 body=body)[0]
    error = value.get('error') or {}
    if error.get('code') not in (None, 'ok'):
        raise ProviderError('rejected')
    data = value.get('data')
    if not isinstance(data, dict):
        raise ProviderError('response', body is not None)
    return data


def publish_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.~-]{4,100}', value):
        raise ValueError('identity')
    return value


def upload_url(url):
    parts = urlsplit(url or '')
    if (parts.scheme != 'https' or parts.hostname != UPLOAD_HOST or parts.port not in (None, 443)
            or not parts.path.startswith('/upload/') or parts.username or parts.password or parts.fragment
            or len(url) > 4096):
        raise ValueError('upload_url')
    return url


def put_file(url, raw, mime):
    upload_url(url)
    if not 0 < len(raw) <= 64 * 1024 * 1024:
        raise ValueError('size')
    session = requests.Session()
    session.trust_env = False
    response = None
    try:
        response = session.put(url, data=raw, timeout=(5, 120), allow_redirects=False, verify=True, stream=True,
                               headers={'Content-Type': mime, 'Content-Length': str(len(raw)),
                                        'Content-Range': 'bytes 0-%d/%d' % (len(raw) - 1, len(raw))})
        if response.status_code not in (200, 201):
            raise ProviderError('upload', True)
    except requests.RequestException:
        raise ProviderError('upload', True) from None
    finally:
        if response is not None:
            response.close()
        session.close()


class Adapter:
    CAPABILITIES = Capabilities(
        label='TikTok',
        hosts=(HOST,),
        operations=('post',),
        formats=('standard', 'carousel'),
        text_limit=CAPTION_LIMIT,
        media_kinds=('image', 'video'),
        max_media=MAX_PHOTOS,
        format_media={'standard': (1, MAX_PHOTOS, ('image', 'video')), 'carousel': (2, MAX_PHOTOS, ('image',))},
        media_required=True,
        needs_public_url=True,
        upload_bytes=True,
        title_limit=PHOTO_TITLE_LIMIT,
        oauth=OAuth(
            authorize_url='https://www.tiktok.com/v2/auth/authorize/',
            token_url='https://open.tiktokapis.com/v2/oauth/token/',
            scopes=('user.info.basic', 'video.publish'),
            scope_separator=',',
            client_id_param='client_key',
        ),
        token_hint='Sign in with TikTok instead: access tokens expire after a day.',
        developer_url='https://developers.tiktok.com/apps/',
    )

    def verify(self, token, account='', kind='organization'):
        user = (api(token, 'user/info/').get('user') or {})
        key = user.get('open_id')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{4,100}', key):
            raise ValueError('profile')
        name = user.get('username') and '@' + user['username'] or user.get('display_name') or key
        return {'id': key, 'name': name[:256], 'kind': 'organization'}

    def oauth_token(self, response, app, account=''):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        return token, {}

    def validate(self, doc):
        if doc['operation'] != 'post':
            raise ValueError('operation')
        media = doc.get('media', [])
        kinds = {m['kind'] for m in media}
        if len(doc['body']) > CAPTION_LIMIT:
            raise ValueError('content')
        if kinds == {'video'}:
            if len(media) != 1 or doc.get('format', 'standard') != 'standard':
                raise ValueError('count')
        elif kinds == {'image'}:
            if not 1 <= len(media) <= MAX_PHOTOS:
                raise ValueError('count')
            if not (doc.get('title') or '').strip():
                raise ValueError('title')
            if any(urlsplit(m.get('url', '')).scheme != 'https' for m in media):
                raise ValueError('media_url')
        else:
            raise ValueError('format')

    def read(self, bundle):
        # TikTok's posting scope cannot list videos or comments.
        if self.verify(bundle['token'])['id'] != bundle['profile']['id']:
            raise ValueError('account')
        return [], 'TikTok offers no API to read comments or messages for this account.'

    def _privacy(self, token):
        info = api(token, 'post/publish/creator_info/query/', {})
        options = info.get('privacy_level_options') or []
        for level in PREFERRED_PRIVACY:
            if level in options:
                return level, info
        raise ValueError('privacy')

    def _status(self, token, key):
        try:
            data = api(token, 'post/publish/status/fetch/', {'publish_id': key})
        except ProviderError:
            # A status read changes nothing; ask again later.
            return 'waiting', None, 'Could not read TikTok\'s status. Continue later.'
        status = data.get('status')
        if status == 'PUBLISH_COMPLETE':
            posted = data.get('publicaly_available_post_id') or data.get('publicly_available_post_id') or []
            return 'sent', str(posted[0]) if posted else key, 'TikTok published the post.'
        if status == 'FAILED':
            return 'failed', '', 'TikTok could not publish this post (%s).' % (data.get('fail_reason') or 'no reason')
        return 'waiting', None, 'Media is processing. Continue when ready.'

    def execute(self, bundle, doc, container=''):
        token, profile = bundle['token'], bundle['profile']
        try:
            self.validate(doc)
            if self.verify(token)['id'] != doc['account'] or doc['account'] != profile['id']:
                raise ValueError('account')
            stage = json.loads(container) if container else {}
            media = doc['media']
            video = media[0]['kind'] == 'video'
            if not stage:
                privacy, info = self._privacy(token)
                if video:
                    raw = bundle['media_bytes'][media[0]['id']]
                    try:
                        data = api(token, 'post/publish/video/init/', {
                            'post_info': {'title': doc['body'], 'privacy_level': privacy},
                            'source_info': {'source': 'FILE_UPLOAD', 'video_size': len(raw),
                                            'chunk_size': len(raw), 'total_chunk_count': 1},
                        })
                    except ProviderError:
                        # Opening the upload creates no visible post.
                        return 'failed', '', 'TikTok did not open the upload. Check the account permissions.'
                    stage = {'publish_id': publish_id(data.get('publish_id')), 'upload': upload_url(data.get('upload_url')),
                             'privacy': privacy}
                    return 'waiting', json.dumps(stage), 'Preparing media.'
                data = api(token, 'post/publish/content/init/', {
                    'post_info': {'title': doc.get('title', '')[:PHOTO_TITLE_LIMIT], 'description': doc['body'],
                                  'privacy_level': privacy},
                    'source_info': {'source': 'PULL_FROM_URL', 'photo_cover_index': 0,
                                    'photo_images': [m['url'] for m in media]},
                    'post_mode': 'DIRECT_POST', 'media_type': 'PHOTO',
                })
                stage = {'publish_id': publish_id(data.get('publish_id')), 'privacy': privacy}
                return 'waiting', json.dumps(stage), 'Preparing media.'
            if stage.get('upload'):
                put_file(stage['upload'], bundle['media_bytes'][media[0]['id']], media[0]['mime'])
                stage.pop('upload')
                return 'waiting', json.dumps(stage), 'Preparing media.'
            outcome, key, note = self._status(token, publish_id(stage['publish_id']))
            if outcome == 'waiting':
                return 'waiting', json.dumps(stage), note
            if outcome == 'sent' and stage.get('privacy') == 'SELF_ONLY':
                note += ' It is visible only to the account owner until the TikTok app passes the audit.'
            return outcome, key or '', note
        except ProviderError as error:
            return (('unknown' if error.uncertain else 'failed'), '',
                    'Check TikTok before retrying.' if error.uncertain
                    else 'The post was not sent. Check the account permissions.')
        except (ValueError, KeyError):
            return 'failed', '', 'Account, media or content could not be verified.'
