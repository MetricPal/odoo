"""Meta GET handshake. Existing POST route owns durable intake and acknowledgement."""
from odoo import http
from odoo.http import request
from psycopg2 import OperationalError


class WhatsAppWebhook(http.Controller):
    @http.route('/omni/inbound/<string:route_key>', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def challenge(self, route_key, **kwargs):
        arguments = request.httprequest.args
        expected = {'hub.mode', 'hub.verify_token', 'hub.challenge'}
        if (len(route_key) != 36 or set(arguments) != expected
                or any(len(arguments.getlist(k)) != 1 or len(arguments[k]) > 256 for k in expected)):
            return request.make_response('Not available', status=404)
        endpoint = request.env['omni.inbound.endpoint'].sudo().search([
            ('route_key', '=', route_key), ('channel_type_id.code', '=', 'whatsapp')], limit=1)
        if not endpoint:
            return request.make_response('Not available', status=404)
        try:
            with request.env.cr.savepoint():
                result = endpoint._whatsapp_challenge(dict(arguments), request.httprequest.base_url)
        except (ValueError, KeyError):
            return request.make_response('Verification rejected', status=403)
        except OperationalError:
            raise  # Let Odoo retry the transaction before returning the challenge.
        except Exception:
            return request.make_response('Verification unavailable', status=503)
        return request.make_response(result, headers=[('Content-Type', 'text/plain; charset=utf-8'),
                                                     ('Cache-Control', 'no-store')])
