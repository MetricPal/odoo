"""What the post editor needs to guide the author: the choices this account
offers, its limits, placeholders, and the data the live preview shows.

Everything comes from the connector's declared capabilities, so the editor,
the submit checks and the platform agree on the same rules.
"""

from odoo import api, fields, models, _

from ..providers import capabilities as rules
from ..providers.registry import capabilities

ICONS = {
    'instagram': 'oi_instagram', 'facebook': 'oi_facebook', 'linkedin': 'oi_linkedin', 'x': 'oi_x',
    'threads': 'oi_threads', 'tiktok': 'oi_tiktok', 'youtube': 'oi_youtube-play', 'pinterest': 'oi_pinterest',
    'discord': 'oi_discord',
}


def _size(value):
    return '%s MB' % format(value / (1024 * 1024), 'g')


class Publication(models.Model):
    _inherit = 'omni.social.publication'

    composer_ui = fields.Json(compute='_compute_composer_ui')
    # The editor hides a choice when the account offers only one option.
    composer_operations = fields.Integer(compute='_compute_composer_ui')
    composer_formats = fields.Integer(compute='_compute_composer_ui')

    @api.depends('connection_id', 'operation', 'format', 'target_id', 'name')
    def _compute_composer_ui(self):
        for row in self:
            ui = row._composer()
            row.composer_ui = ui
            row.composer_operations = len(ui['operations'])
            row.composer_formats = len(ui['formats'])

    def _composer(self):
        caps = capabilities(self.connection_id.provider) if self.connection_id else None
        provider = self.connection_id.provider or ''
        label = caps.label if caps else (self.connection_id.name or _('the platform'))
        operation_labels = dict(self._fields['operation']._description_selection(self.env))
        format_labels = dict(self._fields['format']._description_selection(self.env))
        operations = caps.operations if caps else ('post',)
        formats = caps.formats if caps else ('standard',)
        low, high, kinds = caps.media_rule(self.format) if caps else (0, 1, ('image',))
        story = self.operation == 'post' and self.format == 'story'
        text_limit = caps.limit_for(self.operation) if caps else 2200
        target = self.target_id
        return {
            'ready': bool(caps and self.connection_id),
            'platform': {'code': provider, 'label': label, 'icon': ICONS.get(provider, 'public')},
            'account': {
                'name': self.connection_id.name or '',
                'profile': self.connection_id.profile_name or self.connection_id.name or '',
                'kind': self.connection_id.account_kind or 'organization',
            },
            'operations': [
                {'value': op, 'label': operation_labels.get(op, op), 'description': self._operation_help(op)}
                for op in operations if op in operation_labels
            ],
            'formats': [
                {'value': fmt, 'label': format_labels.get(fmt, fmt),
                 'description': self._format_help(fmt, caps)}
                for fmt in formats if fmt in format_labels
            ] if self.operation == 'post' else [],
            'text': {
                'limit': text_limit,
                'hidden': story,
                'required': not story,
                'placeholder': self._text_placeholder(label, target),
            },
            'title': {
                'limit': caps.title_limit if caps and self.operation == 'post' else 0,
                'hint': _('Shown as the title on %(platform)s, up to %(limit)s characters.',
                          platform=label, limit=caps.title_limit) if caps and caps.title_limit and self.operation == 'post' else '',
            },
            'media': self._media_rules(caps, low, high, kinds) if self.operation == 'post' else {'max': 0},
            'target': {
                'author': target.author or '',
                'body': (target.body or '')[:600],
                'kind': target.kind or '',
            } if target else False,
        }

    def _operation_help(self, operation):
        return {
            'post': _('A new post on the account'),
            'reply': _('Answer a post or comment in public'),
            'message': _('Private answer to someone who wrote in the last 24 hours'),
        }.get(operation, '')

    def _format_help(self, fmt, caps):
        if not caps:
            return ''
        low, high, kinds = caps.media_rule(fmt)
        if fmt == 'story':
            return _('One photo or video, visible for 24 hours. No text.')
        if fmt == 'reel':
            return _('One vertical video, shown with Reels.')
        if fmt == 'carousel':
            what = _('photos or videos') if len(kinds) > 1 else _('photos')
            return _('%(low)s–%(high)s %(what)s people swipe through', low=low, high=high, what=what)
        return self._describe_media(low, high, kinds)

    def _describe_media(self, low, high, kinds):
        both = len(kinds) > 1
        if not high:
            return _('Text only')
        if high == 1:
            one = _('photo or video') if both else (_('video') if kinds == ('video',) else _('photo'))
            return _('Text and one %(what)s', what=one) if low == 0 else _('One %(what)s with a caption', what=one)
        many = _('photos or videos') if both else _('photos')
        if low == 0:
            return _('Text, with up to %(high)s %(what)s', high=high, what=many)
        return _('Up to %(high)s %(what)s with a caption', high=high, what=many)

    def _text_placeholder(self, label, target):
        if self.operation == 'reply':
            return _('Write a public reply to %(author)s…', author=target.author) if target and target.author \
                else _('Write a public reply…')
        if self.operation == 'message':
            return _('Write a private reply…')
        return _('What do you want to say on %(platform)s?', platform=label)

    def _media_rules(self, caps, low, high, kinds):
        short = self.format in ('story', 'carousel')
        seconds = (rules.VIDEO_SECONDS[0], rules.SHORT_VIDEO_SECONDS if short else rules.VIDEO_SECONDS[1])
        photo_bytes = caps.photo_limit() if caps else rules.PHOTO_BYTES
        lines = []
        if 'image' in kinds:
            lines.append(_('Photos: JPEG, PNG or WebP (sent as JPEG), up to %(size)s and %(mp)s megapixels',
                           size=_size(photo_bytes), mp=rules.PHOTO_PIXELS // 1_000_000))
        if 'video' in kinds:
            lines.append(_('Videos: MP4 (H.264 or HEVC, AAC sound), up to %(size)s, %(low)s s – %(high)s, '
                           'at most %(width)s px wide, 23–60 fps',
                           size=_size(rules.VIDEO_BYTES), low=seconds[0],
                           high=('%s s' % seconds[1]) if seconds[1] < 120 else ('%s min' % (seconds[1] // 60)),
                           width=rules.VIDEO_WIDTH))
        if high:
            lines.insert(0, self._describe_count(low, high))
        if caps and caps.needs_public_url:
            lines.append(_('%(platform)s fetches the files from your public address after approval.',
                           platform=caps.label))
        accept = []
        if 'image' in kinds:
            accept += ['image/jpeg', 'image/png', 'image/webp']
        if 'video' in kinds:
            accept.append('video/mp4')
        return {
            'min': low, 'max': high, 'kinds': list(kinds), 'accept': ','.join(accept),
            'photo_bytes': photo_bytes, 'photo_pixels': rules.PHOTO_PIXELS,
            'video_bytes': rules.VIDEO_BYTES, 'video_seconds': list(seconds), 'video_width': rules.VIDEO_WIDTH,
            'rules': lines,
        }

    def _describe_count(self, low, high):
        if low == high:
            return _('Exactly %(count)s file', count=low) if low == 1 else _('Exactly %(count)s files', count=low)
        if low == 0:
            return _('Optional, up to %(high)s file', high=high) if high == 1 else _('Optional, up to %(high)s files', high=high)
        return _('%(low)s to %(high)s files', low=low, high=high)
