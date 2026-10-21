import hashlib
import logging
import secrets
from datetime import timedelta

import werkzeug.urls

from odoo import api, fields, models
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)


VALID_LOGIN_METHODS = {"password", "magic_link", "both", "oauth_only"}
THROTTLE_WINDOW = timedelta(minutes=15)
MAX_REQUESTS_PER_ADDRESS = 10
MAX_LINKS_PER_ACCOUNT = 3


class AuthMagicLink(models.Model):
    _name = "auth.magic.link"
    _description = "Magic Login Link"
    _order = "create_date desc"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        ondelete="cascade",
    )
    token_hash = fields.Char(required=True, index=True, copy=False)
    expires_at = fields.Datetime(required=True, index=True)
    used_at = fields.Datetime(index=True, copy=False)
    create_ip = fields.Char(copy=False)
    user_agent = fields.Char(copy=False)

    _token_hash_unique = models.Constraint(
        "UNIQUE(token_hash)",
        "The magic link token must be unique.",
    )

    @api.model
    def configured_login_method(self):
        method = self.env["ir.config_parameter"].sudo().get_str(
            "auth_magic_link.login_method", "password"
        )
        return method if method in VALID_LOGIN_METHODS else "password"

    @api.model
    def admin_has_valid_email(self):
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        admin = admin.sudo() if admin else admin
        return bool(
            admin
            and admin.active
            and admin.email
            and email_normalize(admin.email)
        )

    @api.model
    def outbound_email_ready(self):
        return bool(
            self.env["ir.mail_server"].sudo().search_count(
                [("active", "=", True)], limit=1
            )
        )

    @api.model
    def admin_has_active_oauth(self):
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        admin = admin.sudo() if admin else admin
        return bool(
            admin
            and admin.active
            and admin.oauth_provider_id
            and admin.oauth_provider_id.enabled
            and admin.oauth_uid
        )

    @api.model
    def effective_login_method(self):
        """Return a safe mode, falling back to password to prevent lockout."""
        method = self.configured_login_method()
        if method in {"magic_link", "both"} and not (
            self.admin_has_valid_email() and self.outbound_email_ready()
        ):
            return "password"
        if method == "oauth_only" and not self.admin_has_active_oauth():
            return "password"
        return method

    @api.model
    def _generate_token(self):
        return secrets.token_urlsafe(48)

    @api.model
    def _hash_token(self, token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @api.model
    def create_login_token(self, user, expires_at, create_ip=None, user_agent=None):
        # Only one active token per user. Issuing a new one invalidates older ones.
        self.sudo().search([
            ("user_id", "=", user.id),
            ("used_at", "=", False),
        ]).unlink()

        raw_token = self._generate_token()
        record = self.sudo().create({
            "user_id": user.id,
            "token_hash": self._hash_token(raw_token),
            "expires_at": expires_at,
            "create_ip": create_ip,
            "user_agent": user_agent,
        })
        return record, raw_token

    @api.model
    def create_for_user(self, user):
        ttl = self.env["ir.config_parameter"].sudo().get_int(
            "auth_magic_link.expiry_minutes", 10
        )
        _record, raw_token = self.create_login_token(
            user,
            fields.Datetime.add(fields.Datetime.now(), minutes=max(1, min(ttl, 60))),
        )
        return raw_token

    @api.model
    def request_allowed(self, remote_addr, user):
        """Per-address and per-account throttle for link requests."""
        Attempt = self.env["auth.magic.link.attempt"].sudo()
        since = fields.Datetime.now() - THROTTLE_WINDOW
        if remote_addr and Attempt.search_count(
            [("remote_addr", "=", remote_addr), ("create_date", ">=", since)],
            limit=MAX_REQUESTS_PER_ADDRESS,
        ) >= MAX_REQUESTS_PER_ADDRESS:
            return False
        if user and Attempt.search_count(
            [("user_id", "=", user.id), ("create_date", ">=", since)],
            limit=MAX_LINKS_PER_ACCOUNT,
        ) >= MAX_LINKS_PER_ACCOUNT:
            return False
        return True

    @api.model
    def record_attempt(self, remote_addr, user):
        self.env["auth.magic.link.attempt"].sudo().create({
            "remote_addr": (remote_addr or "")[:64],
            "user_id": user.id or False,
        })

    @api.model
    def send_login_link(self, user, db, redirect=None, create_ip=None, user_agent=None):
        """Create a token and queue the email. Queued (not inline) sending keeps
        the response time independent of whether the account exists."""
        ttl = self.env["ir.config_parameter"].sudo().get_int("auth_magic_link.expiry_minutes", 10)
        expiry = fields.Datetime.add(fields.Datetime.now(), minutes=max(1, min(ttl, 60)))
        template = self.env.ref("auth_magic_link.mail_template_email_login_v4", raise_if_not_found=False)
        if not template:
            _logger.error("Magic login template is missing")
            return False
        _record, raw_token = self.sudo().create_login_token(
            user, expiry, create_ip=create_ip, user_agent=user_agent)
        base_url = self.env["ir.config_parameter"].sudo().get_str("web.base.url")
        query = {"token": raw_token, "db": db}
        if redirect:
            query["redirect"] = redirect
        login_url = "%s/auth/magic-login?%s" % (base_url.rstrip("/"), werkzeug.urls.url_encode(query))
        admin = self.env.ref("base.user_admin").sudo()
        template.sudo().with_context(login_url=login_url).send_mail(
            user.id,
            force_send=False,
            email_values={"email_to": user.email, "email_from": admin.email_formatted},
        )
        cron = self.env.ref("mail.ir_cron_mail_scheduler_action", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return True

    @api.model
    def get_user(self, raw_token):
        return self.find_valid_token(raw_token).user_id

    @api.model
    def get_login(self, raw_token):
        return self.get_user(raw_token).login or False

    @api.model
    def consume_for_user(self, raw_token, user_id):
        link = self.find_valid_token(raw_token)
        if not link or link.user_id.id != user_id:
            return False
        return bool(self.consume_token(raw_token))

    @api.model
    def consume_token(self, raw_token):
        if not raw_token:
            return self.browse()

        record = self.sudo().search([
            ("token_hash", "=", self._hash_token(raw_token)),
            ("used_at", "=", False),
            ("expires_at", ">", fields.Datetime.now()),
            ("user_id.active", "=", True),
        ], limit=1)

        if not record:
            return self.browse()

        used_at = fields.Datetime.now()
        self.env.cr.execute(
            """
            UPDATE auth_magic_link
               SET used_at = %s
             WHERE id = %s
               AND used_at IS NULL
             RETURNING id
            """,
            [used_at, record.id],
        )
        if not self.env.cr.fetchone():
            return self.browse()
        record.invalidate_recordset(["used_at"])
        return record

    @api.model
    def find_valid_token(self, raw_token):
        """Return the active link without consuming it."""
        if not raw_token:
            return self.browse()

        return self.sudo().search([
            ("token_hash", "=", self._hash_token(raw_token)),
            ("used_at", "=", False),
            ("expires_at", ">", fields.Datetime.now()),
            ("user_id.active", "=", True),
        ], limit=1)

    @api.autovacuum
    def _gc_magic_link_attempts(self):
        self.env["auth.magic.link.attempt"].sudo().search([
            ("create_date", "<", fields.Datetime.now() - THROTTLE_WINDOW),
        ]).unlink()

    @api.autovacuum
    def _gc_magic_links(self):
        cutoff = fields.Datetime.now()
        self.sudo().search([
            "|",
            ("expires_at", "<=", cutoff),
            ("used_at", "!=", False),
        ]).unlink()


class AuthMagicLinkAttempt(models.Model):
    _name = "auth.magic.link.attempt"
    _description = "Magic Link Request Attempt"
    _log_access = True

    remote_addr = fields.Char(index=True)
    user_id = fields.Many2one("res.users", index=True, ondelete="cascade")
