import json
from psycopg2 import OperationalError
from odoo import http
from odoo.http import request
from odoo.addons.omni_channel.controllers.inbound import OmniInboundController


class SlackInboundController(OmniInboundController):
    @http.route()
    def receive(self, route_key, **kwargs):
        endpoint = request.env['omni.inbound.endpoint'].sudo().search([('route_key','=',route_key)], limit=1)
        if not endpoint or endpoint.channel_type_id.code != 'slack':
            return super().receive(route_key, **kwargs)
        if request.httprequest.args or len(route_key) != 36:
            return request.make_response('Not available', status=404)
        raw = request.httprequest.get_data()
        # Only a protocol challenge may bypass the disabled intake check. Signature
        # verification happens inside _slack_challenge before any state change.
        try:
            value = json.loads(raw)
            if isinstance(value, dict) and value.get('type') == 'url_verification':
                with request.env.cr.savepoint():
                    challenge = endpoint._slack_challenge(raw, dict(request.httprequest.headers), request.httprequest.base_url)
                return request.make_response(challenge, headers=[('Content-Type','text/plain')])
        except OperationalError:
            raise
        except Exception:
            return request.make_response('Intake rejected', status=403)
        return super().receive(route_key, **kwargs)
