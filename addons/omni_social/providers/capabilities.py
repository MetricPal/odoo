"""What each social platform can do, declared once by its connector.

The post form, validation, quota meter and setup screens all read this list,
so a platform rule (a character limit, a daily cap, a price) lives in one place.
Nothing here is loaded from the database: connectors declare it in code.
"""

from dataclasses import dataclass, field, asdict
from types import MappingProxyType

OPERATIONS = ('post', 'reply', 'message')
OPERATION_LABELS = {'post': 'posts', 'reply': 'replies', 'message': 'private replies'}


@dataclass(frozen=True)
class OAuth:
    """Authorization-code sign-in. ``client_auth`` is 'body' or 'basic'."""

    authorize_url: str
    token_url: str
    scopes: tuple = ()
    scope_separator: str = ' '
    pkce: bool = False
    client_auth: str = 'body'
    extra: tuple = ()  # extra (key, value) authorize parameters
    client_id_param: str = 'client_id'  # TikTok calls it 'client_key'


@dataclass(frozen=True)
class Capabilities:
    label: str
    hosts: tuple = ()
    operations: tuple = ('post',)
    formats: tuple = ('standard',)
    text_limit: int = 2200
    message_limit: int = 0  # 0 = text_limit
    media_kinds: tuple = ('image',)
    max_media: int = 1
    media_required: bool = False
    # Media is fetched by the platform from the account's public HTTPS address.
    needs_public_url: bool = False
    # Media bytes are uploaded by the connector itself during publishing.
    upload_bytes: bool = False
    # >0: posts carry the subject as a title of at most this many characters (reviewed with the content).
    title_limit: int = 0
    account_kinds: tuple = ('organization',)
    # Rolling 24-hour caps per operation, as published by the platform.
    daily_limits: dict = field(default_factory=dict)
    # Price per operation in USD when the platform charges per call.
    costs: dict = field(default_factory=dict)
    oauth: OAuth | None = None
    token_hint: str = ''
    developer_url: str = ''
    # Extra account identifier asked at connect time (e.g. a Page ID).
    account_label: str = ''
    # Account kinds for which that identifier is required; empty = optional for all.
    account_required_for: tuple = ()

    def asks_account(self, kind):
        if not self.account_label:
            return False
        return not self.account_required_for or kind in self.account_required_for

    def limit_for(self, operation):
        if operation == 'message' and self.message_limit:
            return self.message_limit
        return self.text_limit

    def paid(self):
        return bool(self.costs)

    def as_dict(self):
        data = asdict(self)
        data['oauth'] = bool(self.oauth)
        data['paid'] = self.paid()
        return data

    def summary(self):
        """One readable line of the rules a post must follow."""
        parts = ['up to %s characters' % format(self.text_limit, ',')]
        single = {'image': 'photo', 'video': 'video'}
        if self.media_kinds and self.max_media == 1:
            parts.append('one ' + ' or '.join(single.get(k, k) for k in self.media_kinds))
        elif self.media_kinds and self.max_media:
            kinds = ' and '.join(single.get(k, k) + 's' for k in self.media_kinds)
            parts.append('%s, up to %s files' % (kinds, self.max_media))
        if self.media_required:
            parts.append('media required')
        for operation, count in self.daily_limits.items():
            parts.append('%s %s a day' % (format(count, ','), OPERATION_LABELS.get(operation, operation)))
        return self.label + ': ' + '; '.join(parts)


def frozen(mapping):
    return MappingProxyType(dict(mapping))
