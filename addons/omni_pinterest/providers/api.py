"""Pinterest API v5 for one account and one board.

The board is chosen at connect time (name or ID) and stored with the
verified profile, so the approver sees exactly where the Pin goes. A Pin is
one request; an interrupted request is uncertain and never repeated.
"""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from odoo.addons.omni_social.providers.capabilities import Capabilities, OAuth
from odoo.addons.omni_social.providers.http import ProviderError, call

HOST = 'api.pinterest.com'
TITLE_LIMIT = 100
TEXT_LIMIT = 500
URL = re.compile(r'https://[^\s<>"]{4,2000}')


def pin_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,30}', value):
        raise ValueError('identity')
    return quote(value, safe='')


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        if result.year < 2010 or result > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
        return None


def get(token, path, **params):
    return call(HOST, '/v5/' + path, token, params=params)[0]


def link_of(body):
    """The first https link in the description becomes the Pin's destination."""
    match = URL.search(body or '')
    if not match:
        return ''
    link = match.group(0).rstrip('.,;:!?)')
    parts = urlsplit(link)
    return link if parts.hostname and not parts.username and len(link) <= 2048 else ''


class Adapter:
    CAPABILITIES = Capabilities(
        label='Pinterest',
        hosts=(HOST,),
        operations=('post',),
        formats=('standard', 'carousel'),
        text_limit=TEXT_LIMIT,
        media_kinds=('image',),
        max_media=5,
        format_media={'standard': (1, 1, ('image',)), 'carousel': (2, 5, ('image',))},
        media_required=True,
        needs_public_url=True,
        title_limit=TITLE_LIMIT,
        oauth=OAuth(
            authorize_url='https://www.pinterest.com/oauth/',
            token_url='https://api.pinterest.com/v5/oauth/token',
            scopes=('user_accounts:read', 'boards:read', 'pins:read', 'pins:write'),
            scope_separator=',',
            client_auth='basic',
        ),
        token_hint='Use an access token with boards:read, pins:read and pins:write.',
        developer_url='https://developers.pinterest.com/apps/',
        account_label='Board to pin to (name or ID)',
        account_required_for=('organization',),
    )

    def verify(self, token, account='', kind='organization'):
        me = get(token, 'user_account')
        username = me.get('username')
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', username):
            raise ValueError('profile')
        wanted = (account or '').strip()
        if not wanted:
            raise ValueError('board')
        boards = get(token, 'boards', page_size=100).get('items')
        if not isinstance(boards, list):
            raise ValueError('response')
        matches = [b for b in boards if isinstance(b, dict) and wanted in (b.get('id'), b.get('name'))]
        if len(matches) != 1:
            raise ValueError('board')
        board = matches[0]
        pin_id(board['id'])
        return {
            'id': username, 'name': '%s · %s' % (username, board.get('name') or board['id']),
            'board': board['id'], 'board_name': board.get('name') or '', 'kind': 'organization',
            'account_type': me.get('account_type', ''),
        }

    def oauth_token(self, response, app, account=''):
        token = response.get('access_token')
        if not isinstance(token, str) or not token:
            raise ValueError('token')
        return token, {}

    def validate(self, doc):
        if doc['operation'] != 'post':
            raise ValueError('operation')
        media = doc.get('media', [])
        fmt = doc.get('format', 'standard')
        if fmt == 'standard' and len(media) != 1:
            raise ValueError('count')
        if fmt == 'carousel' and not 2 <= len(media) <= 5:
            raise ValueError('count')
        if fmt not in ('standard', 'carousel') or any(m['kind'] != 'image' for m in media):
            raise ValueError('format')
        if any(urlsplit(m.get('url', '')).scheme != 'https' for m in media):
            raise ValueError('media_url')
        title = doc.get('title', '')
        if not title.strip() or len(title) > TITLE_LIMIT or len(doc['body']) > TEXT_LIMIT:
            raise ValueError('content')

    def read(self, bundle):
        token, profile = bundle['token'], bundle['profile']
        current = self.verify(token, profile['board'])
        if current['id'] != profile['id'] or current['board'] != profile['board']:
            raise ValueError('account')
        pins = get(token, 'boards/%s/pins' % pin_id(profile['board']), page_size=25).get('items')
        if not isinstance(pins, list):
            raise ValueError('response')
        result = []
        for pin in pins[:25]:
            key = pin_id(pin.get('id'))
            result.append({
                'external_key': key, 'kind': 'post', 'author': profile['name'],
                'body': ((pin.get('title') or '') + '\n' + (pin.get('description') or '')).strip()[:10000],
                'permalink': 'https://www.pinterest.com/pin/%s/' % key,
                'occurred_at': stamp(pin.get('created_at')), 'format': 'PIN',
            })
        return result, 'Latest 25 Pins on %s. Pinterest has no comments API.' % (profile.get('board_name') or 'the board')

    def execute(self, bundle, doc, container=''):
        token, profile = bundle['token'], bundle['profile']
        try:
            self.validate(doc)
            current = self.verify(token, profile['board'])
            if current['id'] != doc['account'] or current['board'] != profile['board']:
                raise ValueError('account')
            media = doc['media']
            if len(media) == 1:
                source = {'source_type': 'image_url', 'url': media[0]['url']}
            else:
                source = {'source_type': 'multiple_image_urls',
                          'items': [{'url': m['url'], 'title': doc['title'], 'description': m.get('alt_text', '')}
                                    for m in media]}
            body = {'board_id': profile['board'], 'title': doc['title'], 'description': doc['body'],
                    'alt_text': (media[0].get('alt_text') or '')[:500], 'media_source': source}
            link = link_of(doc['body'])
            if link:
                body['link'] = link
            created = call(HOST, '/v5/pins', token, method='POST', body=body)[0]
            try:
                key = pin_id(created.get('id'))
            except ValueError:
                raise ProviderError('response', True) from None
            # Trial-access apps create Pins only their creator can see (see the README).
            return 'sent', key, 'Pinterest accepted the Pin.'
        except ProviderError as error:
            return (('unknown' if error.uncertain else 'failed'), '',
                    'Check the board before retrying.' if error.uncertain
                    else 'The Pin was not created. Check the account permissions and board.')
        except ValueError:
            return 'failed', '', 'Account, board or content could not be verified.'
