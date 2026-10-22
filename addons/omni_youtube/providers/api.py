"""YouTube Data API v3 for one channel.

Upload is resumable and split in two committed steps: open the upload session
(no video exists yet), then send the bytes. If the second step is interrupted
the result is "check the platform", never a second upload.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import requests

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call

HOST = 'www.googleapis.com'
TITLE_LIMIT = 100
TEXT_LIMIT = 5000
REPLY_LIMIT = 10000


def video_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,20}', value):
        raise ValueError('identity')
    return value


def comment_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{6,100}', value):
        raise ValueError('identity')
    return value


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 2005 or result > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
        return None


def api(token, path, **params):
    return call(HOST, '/youtube/v3/' + path, token, params=params)[0]


def items(result):
    data = result.get('items')
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError('response')
    return data


def session_url(url):
    """Only Google's resumable upload session for videos."""
    parts = urlsplit(url or '')
    query = parse_qs(parts.query)
    if (
        parts.scheme != 'https' or parts.hostname != HOST or parts.port not in (None, 443)
        or parts.path != '/upload/youtube/v3/videos' or parts.username or parts.password or parts.fragment
        or len(query.get('upload_id', [])) != 1 or len(url) > 4096
    ):
        raise ValueError('upload_session')
    return url


def put_video(url, token, raw, mime):
    session_url(url)
    if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
        raise ValueError('token')
    if not 0 < len(raw) <= 64 * 1024 * 1024:
        raise ValueError('size')
    session = requests.Session()
    session.trust_env = False
    response = None
    try:
        response = session.put(url, data=raw, headers={'Authorization': 'Bearer ' + token, 'Content-Type': mime},
                               timeout=(5, 120), allow_redirects=False, verify=True, stream=True)
        body = response.content[:262144]
        if response.status_code not in (200, 201):
            # Bytes were sent; Google may still have created the video.
            raise ProviderError('upload', True)
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ProviderError('response', True)
        return value
    except requests.RequestException:
        raise ProviderError('upload', True) from None
    except ValueError:
        raise ProviderError('response', True) from None
    finally:
        if response is not None:
            response.close()
        session.close()


class Adapter:
    CAPABILITIES = Capabilities(
        label='YouTube',
        hosts=(HOST,),
        operations=('post', 'reply'),
        formats=('standard',),
        text_limit=TEXT_LIMIT,
        reply_limit=REPLY_LIMIT,
        media_kinds=('video',),
        max_media=1,
        format_media={'standard': (1, 1, ('video',))},
        media_required=True,
        upload_bytes=True,
        title_limit=TITLE_LIMIT,
        daily_limits={'post': 100},
        oauth=OAuth(
            authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
            token_url='https://oauth2.googleapis.com/token',
            scopes=('https://www.googleapis.com/auth/youtube.upload',
                    'https://www.googleapis.com/auth/youtube.force-ssl'),
            pkce=True,
            extra=(('access_type', 'offline'), ('prompt', 'consent')),
        ),
        token_hint='Sign in with Google instead: YouTube tokens expire after an hour.',
        developer_url='https://console.cloud.google.com/apis/credentials',
    )

    def verify(self, token, account='', kind='organization'):
        found = items(api(token, 'channels', part='snippet', mine='true'))
        if len(found) != 1:
            raise ValueError('channel')
        channel = found[0]
        if not isinstance(channel.get('id'), str) or not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel['id']):
            raise ValueError('channel')
        return {'id': channel['id'], 'name': (channel.get('snippet') or {}).get('title') or channel['id'],
                'kind': 'organization'}

    def oauth_token(self, response, app, account=''):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        return token, {}

    def validate(self, doc):
        operation, body = doc['operation'], doc['body']
        if operation == 'post':
            media = doc.get('media', [])
            title = doc.get('title', '')
            if len(media) != 1 or media[0]['kind'] != 'video' or doc.get('format', 'standard') != 'standard':
                raise ValueError('video_required')
            if not title.strip() or len(title) > TITLE_LIMIT or '<' in title or '>' in title:
                raise ValueError('title')
            if len(body) > TEXT_LIMIT or '<' in body or '>' in body:
                raise ValueError('content')
        elif operation == 'reply':
            if not body.strip() or len(body) > REPLY_LIMIT:
                raise ValueError('content')
            video_id(doc['root'])
            if doc['target'] != doc['root']:
                comment_id(doc['target'])
        else:
            raise ValueError('operation')

    def read(self, bundle):
        token, profile = bundle['token'], bundle['profile']
        if self.verify(token)['id'] != profile['id']:
            raise ValueError('account')
        missing = []
        started = time.monotonic()
        details = items(api(token, 'channels', part='contentDetails', id=profile['id']))
        uploads = ((details[0].get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads') if details else ''
        if not uploads:
            return [], 'Access unavailable: uploads.'
        entries = items(api(token, 'playlistItems', part='snippet,contentDetails', playlistId=uploads, maxResults=20))
        ids = [video_id((e.get('contentDetails') or {}).get('videoId')) for e in entries]
        stats = {}
        if ids:
            for video in items(api(token, 'videos', part='statistics', id=','.join(ids))):
                stats[video.get('id')] = video.get('statistics') or {}
        result = []
        for entry, key in zip(entries, ids):
            if time.monotonic() - started > 40:
                missing.append('remaining videos (time limit)')
                break
            snippet = entry.get('snippet') or {}
            numbers = stats.get(key, {})
            result.append({
                'external_key': key, 'kind': 'post', 'author': profile['name'],
                'body': ((snippet.get('title') or '') + '\n' + (snippet.get('description') or '')).strip()[:10000],
                'permalink': 'https://www.youtube.com/watch?v=' + key,
                'occurred_at': stamp((entry.get('contentDetails') or {}).get('videoPublishedAt') or snippet.get('publishedAt')),
                'likes': int(numbers.get('likeCount', 0) or 0), 'comments': int(numbers.get('commentCount', 0) or 0),
                'format': 'VIDEO',
            })
            try:
                threads = items(api(token, 'commentThreads', part='snippet', videoId=key, maxResults=50,
                                    textFormat='plainText'))
            except ProviderError:
                missing.append('comments')
                continue
            for thread in threads:
                top = ((thread.get('snippet') or {}).get('topLevelComment') or {})
                info = top.get('snippet') or {}
                if (info.get('authorChannelId') or {}).get('value') == profile['id']:
                    continue
                result.append({
                    'external_key': comment_id(top.get('id')), 'root_key': key, 'kind': 'comment',
                    'body': (info.get('textOriginal') or info.get('textDisplay') or '')[:10000],
                    'author': info.get('authorDisplayName', ''), 'occurred_at': stamp(info.get('publishedAt')),
                })
        note = 'Latest 20 uploads with up to 50 comments each.'
        if missing:
            note += ' Access unavailable: ' + ', '.join(sorted(set(missing))) + '.'
        return result, note

    def execute(self, bundle, doc, container=''):
        token, profile = bundle['token'], bundle['profile']
        try:
            self.validate(doc)
            if self.verify(token)['id'] != doc['account']:
                raise ValueError('account')
            if doc['operation'] == 'reply':
                video = items(api(token, 'videos', part='snippet', id=video_id(doc['root'])))
                if len(video) != 1 or (video[0].get('snippet') or {}).get('channelId') != profile['id']:
                    raise ValueError('owner')
                if doc['target'] == doc['root']:
                    created = call(HOST, '/youtube/v3/commentThreads', token, method='POST', params={'part': 'snippet'},
                                   body={'snippet': {'videoId': doc['root'],
                                                     'topLevelComment': {'snippet': {'textOriginal': doc['body']}}}})[0]
                else:
                    created = call(HOST, '/youtube/v3/comments', token, method='POST', params={'part': 'snippet'},
                                   body={'snippet': {'parentId': doc['target'], 'textOriginal': doc['body']}})[0]
                return 'sent', comment_id(created.get('id')), 'YouTube accepted the reply.'
            item = doc['media'][0]
            if not container:
                raw = bundle['media_bytes'][item['id']]
                try:
                    _body, headers = call(HOST, '/upload/youtube/v3/videos', token, method='POST',
                                          params={'uploadType': 'resumable', 'part': 'snippet,status'},
                                          headers={'X-Upload-Content-Type': item['mime'],
                                                   'X-Upload-Content-Length': str(len(raw))},
                                          body={'snippet': {'title': doc['title'], 'description': doc['body']},
                                                'status': {'privacyStatus': 'public',
                                                           'selfDeclaredMadeForKids': False}})
                except ProviderError:
                    # Opening a session creates nothing on YouTube, so this is a plain failure.
                    return 'failed', '', 'YouTube did not start the upload. Check the channel permissions.'
                location = {k.lower(): v for k, v in headers.items()}.get('location', '')
                # No video exists until the bytes arrive; a failed session can be opened again.
                return 'waiting', session_url(location), 'Preparing media.'
            created = put_video(session_url(container), token, bundle['media_bytes'][item['id']], item['mime'])
            key = video_id(created.get('id'))
            privacy = ((created.get('status') or {}).get('privacyStatus'))
            note = 'YouTube accepted the video.'
            if privacy == 'private':
                note += ' YouTube kept it private (the Google project has not passed the YouTube audit yet).'
            return 'sent', key, note
        except ProviderError as error:
            return (('unknown' if error.uncertain else 'failed'), '',
                    'Check YouTube Studio before retrying.' if error.uncertain
                    else 'Action was not sent. Check the channel permissions.')
        except (ValueError, KeyError):
            return 'failed', '', 'Channel, video or destination could not be verified.'
