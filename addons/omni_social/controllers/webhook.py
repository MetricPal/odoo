import json
import re
from odoo import http
from odoo.http import request
from ..providers import webhook


class SocialWebhook(http.Controller):
    @http.route('/omni/social/webhook/<route>', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def incoming(self, route, **params):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', route):
            return request.not_found()
        account = (
            request.env['omni.social.connection']
            .sudo()
            .search(
                [
                    ('webhook_route', '=', route),
                    ('webhook_enabled', '=', True),
                    ('active', '=', True),
                    ('connected', '=', True),
                ],
                limit=1,
            )
        )
        if not account:
            return request.not_found()
        bundle = account._bundle()
        secret = bundle.get('webhook_secret', '')
        if request.httprequest.method == 'GET':
            try:
                answer = webhook.challenge(account.provider, secret, account.webhook_verify, params)
            except ValueError:
                return request.make_response('', status=403)
            return request.make_response(
                json.dumps(answer) if isinstance(answer, dict) else answer,
                headers=[
                    ('Content-Type', 'application/json' if isinstance(answer, dict) else 'text/plain'),
                    ('Cache-Control', 'no-store'),
                ],
            )
        # Read at most the bounded body size, including requests without Content-Length.
        raw = request.httprequest.stream.read(524289)
        header = request.httprequest.headers.get(
            'X-Hub-Signature-256' if account.provider == 'instagram' else 'X-LI-Signature', ''
        )
        if not webhook.signature(account.provider, secret, raw, header):
            return request.make_response('', status=403)
        try:
            keys = webhook.hints(account.provider, bundle['profile'], raw)
        except (ValueError, KeyError, TypeError):
            return request.make_response('', status=400)
        account._enqueue_webhook(keys)
        return request.make_response('', status=200)
