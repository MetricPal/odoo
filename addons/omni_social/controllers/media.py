"""Serve only approved immutable media belonging to a current publishing claim."""

import hashlib
import re
from odoo import http, fields
from odoo.http import request


class SocialMedia(http.Controller):
    @http.route(
        ['/omni/social/media/<token>', '/omni/social/media/<token>/<int:index>'],
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def image(self, token, index=None, **kw):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return request.not_found()
        row = (
            request.env['omni.social.publication']
            .sudo()
            .search(
                [
                    ('media_token', '=', token),
                    ('state', 'in', ['executing', 'waiting']),
                    ('expires_at', '>', fields.Datetime.now()),
                ],
                limit=1,
            )
        )
        if not row or not row.connection_id.active or row.payload.get('revision') != row.connection_id.revision:
            return request.not_found()
        mime = 'image/jpeg'
        if index is None:
            if not row.image:
                return request.not_found()
            raw = row.image.content
            expected = row.payload.get('image_digest')
        else:
            manifest = row.payload.get('media', [])
            if not 0 <= index < len(manifest):
                return request.not_found()
            item = manifest[index]
            media = row.media_ids.filtered(lambda m: m.id == item['id'])
            if not media:
                return request.not_found()
            raw = media.file.content
            expected = item['digest']
            mime = item['mime']
        if hashlib.sha256(raw).hexdigest() != expected:
            return request.not_found()
        return request.make_response(
            raw,
            headers=[
                ('Content-Type', mime),
                ('Content-Length', str(len(raw))),
                ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'),
            ],
        )
