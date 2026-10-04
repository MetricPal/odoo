from werkzeug.urls import url_encode

from odoo import http
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.http import request


class BrandingAuthSignupHome(AuthSignupHome):
    def _use_v_as_db_alias(self, kw):
        if not request.params.get("db") and request.params.get("v"):
            db_name = request.params["v"].strip()
            request.params["db"] = db_name
            kw.setdefault("db", db_name)

    def _redirect_db_to_v(self):
        if request.httprequest.method != "GET":
            return None
        if not request.params.get("db") or request.params.get("v"):
            return None

        args = request.httprequest.args.copy()
        db_name = args.pop("db").strip()
        args["v"] = db_name
        query_string = url_encode(args)
        url = request.httprequest.path
        if query_string:
            url = f"{url}?{query_string}"
        return request.redirect(url, 302)

    @http.route()
    def web_login(self, *args, **kw):
        if redirect := self._redirect_db_to_v():
            return redirect
        self._use_v_as_db_alias(kw)
        return super().web_login(*args, **kw)

    @http.route()
    def web_auth_signup(self, *args, **kw):
        if redirect := self._redirect_db_to_v():
            return redirect
        self._use_v_as_db_alias(kw)
        return super().web_auth_signup(*args, **kw)

    @http.route()
    def web_auth_reset_password(self, *args, **kw):
        if redirect := self._redirect_db_to_v():
            return redirect
        self._use_v_as_db_alias(kw)
        return super().web_auth_reset_password(*args, **kw)
