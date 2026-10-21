from psycopg2 import OperationalError

from odoo import http
from odoo.http import request

from odoo.addons.omni_channel.providers.inbound import MAX_BODY, IngressRejected


HANDSHAKE_KEYS = {"hub.mode", "hub.verify_token", "hub.challenge"}


class OmniInboundController(http.Controller):
    @http.route(
        "/omni/inbound/<string:route_key>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def challenge(self, route_key, **kwargs):
        """Meta-style GET handshake on the same callback URL as intake.

        A connector opts in by defining ``_<channel type code>_challenge`` on
        ``omni.inbound.endpoint``; it returns the challenge text or raises.
        """
        arguments = request.httprequest.args
        if (
            len(route_key) != 36
            or set(arguments) != HANDSHAKE_KEYS
            or any(len(arguments.getlist(k)) != 1 or len(arguments[k]) > 256 for k in HANDSHAKE_KEYS)
        ):
            return request.make_response("Not available", status=404)
        endpoint = (
            request.env["omni.inbound.endpoint"]
            .sudo()
            .search([("route_key", "=", route_key)], limit=1)
        )
        code = endpoint.channel_type_id.code if endpoint else ""
        handler = getattr(endpoint, "_%s_challenge" % code, None) if code and code.isidentifier() else None
        if not callable(handler):
            return request.make_response("Not available", status=404)
        try:
            with request.env.cr.savepoint():
                result = handler(dict(arguments), request.httprequest.base_url)
        except (ValueError, KeyError):
            return request.make_response("Verification rejected", status=403)
        except OperationalError:
            raise  # Let Odoo retry the transaction before returning the challenge.
        except Exception:  # noqa: BLE001 - no provider detail disclosure
            return request.make_response("Verification unavailable", status=503)
        return request.make_response(
            result,
            headers=[("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")],
        )

    @http.route(
        "/omni/inbound/<string:route_key>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
        max_content_length=MAX_BODY,
    )
    def receive(self, route_key, **kwargs):
        # Deployment must bind the database by host/dbfilter. No database selector here.
        if request.httprequest.args or len(route_key) != 36:
            return request.make_response("Not available", status=404)
        endpoint = (
            request.env["omni.inbound.endpoint"]
            .sudo()
            .search([("route_key", "=", route_key)], limit=1)
        )
        if not endpoint or not endpoint._allowed():
            return request.make_response("Not available", status=404)
        raw = request.httprequest.get_data()
        try:
            with request.env.cr.savepoint():
                endpoint._receive(raw, dict(request.httprequest.headers))
        except IngressRejected as rejection:
            code = str(rejection)
            status = (
                429
                if code == "rate"
                else 503
                if code == "disabled"
                else 400
                if code
                in (
                    "size",
                    "structure",
                    "schema",
                    "events",
                    "key",
                    "body",
                    "timestamp",
                    "kind",
                    "invalid",
                )
                else 403
            )
            return request.make_response("Intake rejected", status=status)
        except OperationalError:
            raise  # Odoo transaction retry occurs before acknowledgement; no external side effect.
        except Exception:  # noqa: BLE001 - no provider payload/exception disclosure
            return request.make_response("Intake unavailable", status=503)
        # Odoo's HTTP retrying wrapper commits before returning the response.
        return request.make_response("Accepted", status=200)
