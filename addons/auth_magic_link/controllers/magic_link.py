import logging

import werkzeug.urls

from odoo import _, fields, http
from odoo.addons.auth_oauth.controllers.main import OAuthLogin
from odoo.addons.web.controllers.utils import ensure_db
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.http.session import authenticate

_logger = logging.getLogger(__name__)


def _effective_mode():
    return request.env["auth.magic.link"].sudo().effective_login_method()


def _admin_has_valid_email():
    return request.env["auth.magic.link"].sudo().admin_has_valid_email()


def _outbound_email_ready():
    return request.env["auth.magic.link"].sudo().outbound_email_ready()


def _admin_has_active_oauth():
    return request.env["auth.magic.link"].sudo().admin_has_active_oauth()


class EmailAuthLogin(OAuthLogin):
    # The website module republishes /web/login with website=True. This module
    # deliberately loads after website and restores the standalone web login
    # context so website-specific views cannot wrap the authentication form.
    @http.route(website=False, auth="none", sitemap=False)
    def web_login(self, *args, **kw):
        mode = _effective_mode()

        if request.httprequest.method == "POST":
            if "email_login" in request.params:
                return self._magic_link_request(kw.get("redirect"))

            requested_type = request.params.get("type") or "password"
            if requested_type == "password" and mode not in ("password", "both"):
                response = super().web_login(*args, **kw)
                if response.is_qweb:
                    response.qcontext["error"] = _(
                        "Password login is disabled by the system administrator."
                    )
                    self._add_auth_context(response, mode)
                return response

        response = super().web_login(*args, **kw)
        if response.is_qweb:
            self._add_auth_context(response, mode)
        return response

    def _add_auth_context(self, response, mode):
        response.qcontext["auth_email_login_mode"] = mode
        response.qcontext["auth_magic_link_magic_view"] = (
            mode == "both" and request.params.get("auth_view") == "magic"
        )
        response.qcontext["auth_email_alert_view"] = (
            "magic" if request.params.get("auth_view") == "magic" else "password"
        )
        response.qcontext["auth_email_admin_ready"] = _outbound_email_ready()
        response.qcontext["auth_oauth_admin_ready"] = _admin_has_active_oauth()

    @http.route(
        "/auth/magic-link/user-email",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        website=False,
    )
    def user_email(self, login=None, **kwargs):
        mode = _effective_mode()
        if mode not in ("magic_link", "both") or not login:
            return {"email": ""}
        user = request.env["res.users"].sudo().search(
            [("active", "=", True), ("login", "=", login)],
            limit=1,
        )
        return {"email": user.email or "" if user else ""}

    def _magic_link_request(self, redirect=None):
        mode = _effective_mode()
        if mode not in ("magic_link", "both"):
            return request.redirect("/web/login", 303)

        email = (request.params.get("email_login") or "").strip()
        if email:
            users = request.env["res.users"].sudo().search(
                [("active", "=", True), ("email", "=ilike", email)],
                limit=2,
            )
            if len(users) == 1 and users.email:
                ttl = request.env["ir.config_parameter"].sudo().get_int(
                    "auth_magic_link.expiry_minutes", 10
                )
                expiry = fields.Datetime.add(
                    fields.Datetime.now(),
                    minutes=max(1, min(ttl, 60)),
                )
                token_record, raw_token = request.env["auth.magic.link"].sudo().create_login_token(
                    users,
                    expiry,
                    create_ip=request.httprequest.remote_addr,
                    user_agent=request.httprequest.user_agent.string[:512],
                )
                base_url = request.env["ir.config_parameter"].sudo().get_str(
                    "web.base.url"
                )
                query = {"token": raw_token, "db": request.db}
                if redirect:
                    query["redirect"] = redirect
                login_url = "%s/auth/magic-login?%s" % (
                    base_url.rstrip("/"),
                    werkzeug.urls.url_encode(query),
                )
                template = request.env.ref(
                    "auth_magic_link.mail_template_email_login_v4",
                    raise_if_not_found=False,
                )
                try:
                    if template:
                        admin = request.env.ref("base.user_admin").sudo()
                        template.sudo().with_context(login_url=login_url).send_mail(
                            users.id,
                            force_send=True,
                            raise_exception=True,
                            email_values={
                                "email_to": users.email,
                                "email_from": admin.email_formatted,
                            },
                        )
                    else:
                        token_record.unlink()
                        _logger.error("Magic login template is missing")
                except Exception:
                    token_record.unlink()
                    _logger.exception("Failed to send magic login email")

        query = {
            "message": _(
                "If an account exists for that email, a login link has been sent."
            ),
            "auth_view": "magic",
        }
        if redirect:
            query["redirect"] = redirect
        return request.redirect(
            "/web/login?%s" % werkzeug.urls.url_encode(query), 303
        )


class EmailLoginController(http.Controller):
    @http.route(
        "/auth/magic-login",
        type="http",
        auth="public",
        methods=["GET"],
        website=False,
        sitemap=False,
        readonly=False,
    )
    def email_login(self, token=None, redirect=None, **kwargs):
        ensure_db()
        try:
            if _effective_mode() not in ("magic_link", "both") or not token:
                raise AccessDenied()

            link = request.env["auth.magic.link"].sudo().find_valid_token(token)
            if not link:
                raise AccessDenied()

            authenticate(
                request.session,
                request.env,
                {"login": link.user_id.login, "token": token, "type": "magic_link"},
            )
            target = (
                redirect
                if redirect and redirect.startswith("/") and not redirect.startswith("//")
                else "/odoo"
            )
            return request.redirect(target, 303)
        except AccessDenied:
            _logger.info("Invalid or expired magic login token")
            return request.redirect(
                "/web/login?%s"
                % werkzeug.urls.url_encode({
                    "error": _("This login link is invalid or has expired."),
                    "auth_view": "magic",
                }),
                303,
            )
