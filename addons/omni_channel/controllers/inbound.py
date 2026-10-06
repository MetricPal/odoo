from psycopg2 import OperationalError

from odoo import http
from odoo.http import request

from odoo.addons.omni_channel.providers.inbound import MAX_BODY, IngressRejected


class OmniInboundController(http.Controller):
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
