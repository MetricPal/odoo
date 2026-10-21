import logging
from urllib.parse import urlsplit

import werkzeug.urls

from odoo import _, fields, http
from odoo.addons.auth_oauth.controllers.main import OAuthLogin
from odoo.addons.web.controllers.utils import ensure_db
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.http.session import authenticate
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

DEFAULT_LANDING = "/odoo"


def MAGIC_LINK_SENT_MESSAGE():
    return _("If an account exists for that email, a sign-in link is on its way. It works once and expires soon.")


def _effective_mode():
    return request.env["auth.magic.link"].sudo().effective_login_method()


def _outbound_email_ready():
    return request.env["auth.magic.link"].sudo().outbound_email_ready()


def _admin_has_active_oauth():
    return request.env["auth.magic.link"].sudo().admin_has_active_oauth()


def safe_redirect(target):
    """Return ``target`` only when it is a same-site absolute path.

    Rejects scheme/host URLs, protocol-relative ``//host``, backslash variants
    browsers normalise to ``//host`` (``/\\host``), and control characters.
    """
    if not isinstance(target, str) or not target.startswith("/"):
        return None
    if "\\" in target or any(ord(char) < 32 or ord(char) == 127 for char in target):
        return None
    try:
        parts = urlsplit(target)
    except ValueError:
        return None
    if parts.scheme or parts.netloc or target.startswith("//"):
        return None
    return target


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
        magic_view = request.params.get("auth_view") == "magic"
        response.qcontext["auth_magic_link_magic_view"] = mode == "both" and magic_view
        response.qcontext["auth_email_alert_view"] = "magic" if magic_view else "password"
        response.qcontext["auth_email_admin_ready"] = _outbound_email_ready()
        response.qcontext["auth_oauth_admin_ready"] = _admin_has_active_oauth()
        if magic_view:
            # Never echo caller-supplied text under the "Check your email" heading.
            response.qcontext["message"] = (
                MAGIC_LINK_SENT_MESSAGE() if request.params.get("magic_sent") == "1" else None
            )

    def _magic_link_request(self, redirect=None):
        mode = _effective_mode()
        if mode not in ("magic_link", "both"):
            return request.redirect("/web/login", 303)

        redirect = safe_redirect(redirect)
        normalized = email_normalize((request.params.get("email_login") or "").strip())
        remote_addr = request.httprequest.remote_addr
        Link = request.env["auth.magic.link"].sudo()
        # Exact, normalised match: no wildcard semantics from user input.
        users = request.env["res.users"].sudo().search(
            [("active", "=", True), ("partner_id.email_normalized", "=", normalized)],
            limit=2,
        ) if normalized else request.env["res.users"]
        user = users if len(users) == 1 else request.env["res.users"]
        # Throttle by address and by account. The response never changes, so
        # neither the limit nor the account's existence is observable.
        if Link.request_allowed(remote_addr, user):
            Link.record_attempt(remote_addr, user)
            if user:
                Link.send_login_link(
                    user,
                    db=request.db,
                    redirect=redirect,
                    create_ip=remote_addr,
                    user_agent=request.httprequest.user_agent.string[:512],
                )

        query = {"auth_view": "magic", "magic_sent": "1"}
        if redirect:
            query["redirect"] = redirect
        return request.redirect(
            "/web/login?%s" % werkzeug.urls.url_encode(query), 303
        )


class EmailLoginController(http.Controller):
    def _invalid_link(self):
        _logger.info("Invalid or expired magic login token")
        return request.redirect(
            "/web/login?%s"
            % werkzeug.urls.url_encode({
                "error": _("This login link is invalid or has expired."),
                "auth_view": "magic",
            }),
            303,
        )

    @http.route(
        "/auth/magic-login",
        type="http",
        auth="public",
        methods=["GET"],
        website=True,
        sitemap=False,
    )
    def email_login_confirm(self, token=None, redirect=None, **kwargs):
        """Show a confirmation page. Mail scanners and link previews issue GET
        requests; only the explicit POST below consumes the token."""
        ensure_db()
        if _effective_mode() not in ("magic_link", "both") or not token:
            return self._invalid_link()
        link = request.env["auth.magic.link"].sudo().find_valid_token(token)
        if not link:
            return self._invalid_link()
        response = request.render("auth_magic_link.magic_login_confirm", {
            "token": token,
            "redirect": safe_redirect(redirect) or "",
            "magic_user_name": link.user_id.name,
            "disable_footer": True,
        })
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @http.route(
        "/auth/magic-login",
        type="http",
        auth="public",
        methods=["POST"],
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
        except AccessDenied:
            return self._invalid_link()
        return request.redirect(safe_redirect(redirect) or DEFAULT_LANDING, 303)
