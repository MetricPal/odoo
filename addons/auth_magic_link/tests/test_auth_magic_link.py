from lxml import html

from odoo import fields
from odoo.exceptions import AccessDenied, AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


class MagicLinkCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="magic-user@example.invalid",
            groups="base.group_user",
        )

    def _set_mode(self, mode):
        self.env["ir.config_parameter"].sudo().set_str(
            "auth_magic_link.login_method", mode
        )

    def _make_email_ready(self):
        self.env.ref("base.user_admin").sudo().email = "admin@example.invalid"
        self.env["ir.mail_server"].sudo().search([]).write({"active": False})
        return self.env["ir.mail_server"].sudo().create({
            "name": "Magic Link Test SMTP",
            "smtp_host": "localhost",
        })


@tagged("at_install", "-post_install")
class TestMagicLink(MagicLinkCase):
    def test_token_is_hashed_and_single_use(self):
        link, raw_token = self.env["auth.magic.link"].create_login_token(
            self.user,
            fields.Datetime.add(fields.Datetime.now(), minutes=10),
        )

        self.assertNotEqual(link.token_hash, raw_token)
        self.assertEqual(
            self.env["auth.magic.link"].find_valid_token(raw_token), link
        )
        self.assertEqual(
            self.env["auth.magic.link"].consume_token(raw_token), link
        )
        self.assertTrue(link.used_at)
        self.assertFalse(self.env["auth.magic.link"].consume_token(raw_token))

    def test_expired_token_is_rejected(self):
        _link, raw_token = self.env["auth.magic.link"].create_login_token(
            self.user,
            fields.Datetime.add(fields.Datetime.now(), minutes=-1),
        )
        self.assertFalse(self.env["auth.magic.link"].consume_token(raw_token))

    def test_authentication_pipeline_and_replay_rejection(self):
        self._make_email_ready()
        self._set_mode("magic_link")
        _link, raw_token = self.env["auth.magic.link"].create_login_token(
            self.user,
            fields.Datetime.add(fields.Datetime.now(), minutes=10),
        )
        credential = {"type": "magic_link", "token": raw_token}

        anonymous_env = self.env(user=None, su=False)
        auth_info = anonymous_env["res.users"].authenticate(
            credential, {"interactive": True}
        )

        self.assertEqual(auth_info["uid"], self.user.id)
        self.assertEqual(credential["login"], self.user.login)
        with self.assertRaises(AccessDenied):
            self.env["res.users"].authenticate(
                {"type": "magic_link", "token": raw_token},
                {"interactive": True},
            )

    def test_unsafe_magic_mode_falls_back_to_password(self):
        self.env.ref("base.user_admin").sudo().email = "admin@example.invalid"
        self.env["ir.mail_server"].sudo().search([]).write({"active": False})
        self._set_mode("magic_link")

        self.assertEqual(
            self.env["auth.magic.link"].effective_login_method(), "password"
        )
        self._make_email_ready()
        self.assertEqual(
            self.env["auth.magic.link"].effective_login_method(), "magic_link"
        )

    def test_settings_reject_unsafe_magic_mode(self):
        self.env["ir.mail_server"].sudo().search([]).write({"active": False})
        settings = self.env["res.config.settings"].create({
            "auth_login_method": "magic_link",
            "auth_magic_link_expiry_minutes": 10,
        })
        with self.assertRaises(ValidationError):
            settings.set_values()

    def test_oauth_only_blocks_interactive_password_login(self):
        provider = self.env["auth.oauth.provider"].create({
            "name": "Magic Link Test OAuth",
            "client_id": "test-client",
            "auth_endpoint": "https://example.invalid/authorize",
            "validation_endpoint": "https://example.invalid/userinfo",
            "body": "Test OAuth",
            "enabled": True,
        })
        self.env.ref("base.user_admin").sudo().write({
            "oauth_provider_id": provider.id,
            "oauth_uid": "admin-test-oauth",
        })
        self._set_mode("oauth_only")

        with self.assertRaises(AccessDenied):
            self.env["res.users"].authenticate(
                {
                    "type": "password",
                    "login": self.user.login,
                    "password": self.user.login,
                },
                {"interactive": True},
            )

    def test_dedicated_settings_sync_parameters(self):
        self._make_email_ready()
        settings = self.env.ref(
            "auth_magic_link.authentication_settings_singleton"
        )
        settings.write({
            "auth_login_method": "both",
            "auth_magic_link_ttl": 12,
        })

        params = self.env["ir.config_parameter"].sudo()
        self.assertEqual(params.get_str("auth_magic_link.login_method"), "both")
        self.assertEqual(params.get_int("auth_magic_link.expiry_minutes"), 12)

    def test_non_admin_cannot_read_tokens(self):
        link, _raw_token = self.env["auth.magic.link"].create_login_token(
            self.user,
            fields.Datetime.add(fields.Datetime.now(), minutes=10),
        )
        with self.assertRaises(AccessError):
            link.with_user(self.user).check_access("read")


@tagged("post_install", "-at_install")
class TestMagicLinkHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.user_admin").sudo().email = "admin@example.invalid"
        cls.env["ir.mail_server"].sudo().search([]).write({"active": False})
        cls.env["ir.mail_server"].sudo().create({
            "name": "Magic Link HTTP Test SMTP",
            "smtp_host": "localhost",
        })
        cls.env["ir.config_parameter"].sudo().set_str(
            "auth_magic_link.login_method", "magic_link"
        )

    def _login_document(self):
        response = self.url_open("/web/login")
        response.raise_for_status()
        return html.fromstring(response.content), response

    def _assert_standalone_auth_layout(self, document):
        login_card = document.xpath("//div[contains(@class, 'o_database_list')]")
        self.assertTrue(login_card)
        self.assertIn("bg-transparent", login_card[0].get("class", "").split())
        self.assertNotIn("bg-100", login_card[0].get("class", "").split())
        card_body = login_card[0].xpath("./div[contains(@class, 'card-body')]")
        self.assertTrue(card_body)
        self.assertIn("bg-transparent", card_body[0].get("class", "").split())
        self.assertFalse(document.xpath(
            "//div[contains(@class, 'oe_website_login_container')]"
        ))
        self.assertFalse(document.xpath("//header[@id='top']"))
        self.assertFalse(document.xpath("//footer[@id='bottom']"))

    def test_authentication_settings_widget_renders(self):
        selector = ".o_auth_login_method_options input[type='radio']"
        self.browser_js(
            "/odoo/action-auth_magic_link.action_authentication_settings",
            """
                const inputs = document.querySelectorAll(
                    ".o_auth_login_method_options input[type='radio']"
                );
                if (inputs.length === 4) {
                    console.log("test successful");
                } else {
                    console.error(
                        `Expected four authentication methods, found ${inputs.length}`
                    );
                }
            """,
            ready=f"document.querySelectorAll(\"{selector}\").length === 4",
            login="admin",
        )

    def test_both_mode_renders_password_and_magic_forms(self):
        self.env["ir.config_parameter"].sudo().set_str(
            "auth_magic_link.login_method", "both"
        )
        document, _response = self._login_document()
        self.assertTrue(document.xpath("//form[@data-captcha='login']"))
        self.assertTrue(document.xpath("//input[@name='login']"))
        self.assertTrue(document.xpath("//input[@name='password']"))
        self.assertTrue(document.xpath("//input[@name='email_login']"))
        self.assertTrue(document.xpath(
            "//button[contains(@class, 'o_auth_method_toggle')]"
        ))

    def test_login_uses_standalone_web_layout(self):
        document, _response = self._login_document()
        self._assert_standalone_auth_layout(document)

    def test_reset_password_uses_standalone_web_layout(self):
        self.env["ir.config_parameter"].sudo().set_bool(
            "auth_signup.reset_password", True
        )
        response = self.url_open("/web/reset_password")
        response.raise_for_status()
        document = html.fromstring(response.content)
        self.assertTrue(document.xpath("//form[@data-captcha='password_reset']"))
        self._assert_standalone_auth_layout(document)

    def test_signup_uses_standalone_web_layout(self):
        self.env["ir.config_parameter"].sudo().set_str(
            "auth_signup.invitation_scope", "b2c"
        )
        self.env["website"].search([], limit=1).auth_signup_uninvited = "b2c"
        response = self.url_open("/web/signup")
        response.raise_for_status()
        document = html.fromstring(response.content)
        self.assertTrue(document.xpath("//form[@data-captcha='signup']"))
        self._assert_standalone_auth_layout(document)

    def test_oauth_only_renders_provider_without_local_forms(self):
        provider = self.env["auth.oauth.provider"].create({
            "name": "Magic Link HTTP OAuth",
            "client_id": "http-test-client",
            "auth_endpoint": "https://example.invalid/authorize",
            "validation_endpoint": "https://example.invalid/userinfo",
            "body": "HTTP Test OAuth",
            "enabled": True,
        })
        self.env.ref("base.user_admin").sudo().write({
            "oauth_provider_id": provider.id,
            "oauth_uid": "admin-http-test-oauth",
        })
        self.env["ir.config_parameter"].sudo().set_str(
            "auth_magic_link.login_method", "oauth_only"
        )

        document, _response = self._login_document()
        self.assertTrue(document.xpath("//form[@data-captcha='login']"))
        self.assertFalse(document.xpath("//input[@name='login']"))
        self.assertFalse(document.xpath("//input[@name='password']"))
        self.assertFalse(document.xpath("//input[@name='email_login']"))
        self.assertTrue(
            document.xpath("//div[contains(@class, 'o_login_auth')]//span")
        )

    def test_login_page_and_unknown_email_request(self):
        document, response = self._login_document()
        self.assertTrue(document.xpath("//input[@name='email_login']"))
        self.assertFalse(document.xpath("//input[@name='login']"))
        csrf_token = document.xpath("//input[@name='csrf_token']")[0].get("value")

        response = self.url_open(
            "/web/login",
            data={
                "csrf_token": csrf_token,
                "email_login": "does-not-exist@example.invalid",
                "type": "magic_link",
                "redirect": "/odoo",
            },
        )
        response.raise_for_status()
        self.assertIn(b"If an account exists for that email, a sign-in link is on its way.", response.content)
        spoofed = self.url_open("/web/login?auth_view=magic&message=Call+us+now")
        self.assertNotIn(b"Call us now", spoofed.content)


@tagged("post_install", "-at_install")
class TestMagicLinkHardening(MagicLinkCase):
    def test_safe_redirect(self):
        from odoo.addons.auth_magic_link.controllers.magic_link import safe_redirect
        self.assertEqual(safe_redirect("/odoo/action-1?x=1"), "/odoo/action-1?x=1")
        for unsafe in ("//evil.example", "/\\evil.example", "/\\/evil.example", "https://evil.example",
                       "evil.example", "/ok\nLocation: x", "/\t/evil.example", "", None):
            self.assertIsNone(safe_redirect(unsafe), unsafe)

    def test_throttle_per_account_and_address(self):
        Link = self.env["auth.magic.link"]
        for _i in range(3):
            self.assertTrue(Link.request_allowed("10.0.0.1", self.user))
            Link.record_attempt("10.0.0.1", self.user)
        self.assertFalse(Link.request_allowed("10.0.0.2", self.user))
        nobody = self.env["res.users"]
        for _i in range(7):
            Link.record_attempt("10.0.0.9", nobody)
        self.assertTrue(Link.request_allowed("10.0.0.9", nobody))
        Link.record_attempt("10.0.0.9", nobody)
        Link.record_attempt("10.0.0.9", nobody)
        Link.record_attempt("10.0.0.9", nobody)
        self.assertFalse(Link.request_allowed("10.0.0.9", nobody))

    def test_send_login_link_queues_mail(self):
        self._make_email_ready()
        self.user.email = "magic-user@example.invalid"
        mails = self.env["mail.mail"].sudo().search_count([])
        self.assertTrue(self.env["auth.magic.link"].send_login_link(self.user, db=self.env.cr.dbname, redirect="/odoo"))
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails + 1)
        mail = self.env["mail.mail"].sudo().search([], order="id desc", limit=1)
        self.assertEqual(mail.state, "outgoing")
        self.assertIn("/auth/magic-login?token=", mail.body_html)


@tagged("post_install", "-at_install")
class TestMagicLinkHttpHardening(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="magic-http@example.invalid", groups="base.group_user",
                                 email="magic-http@example.invalid")
        cls.env.ref("base.user_admin").sudo().email = "admin@example.invalid"
        cls.env["ir.mail_server"].sudo().create({"name": "Magic Link HTTP SMTP", "smtp_host": "localhost"})
        cls.env["ir.config_parameter"].sudo().set_str("auth_magic_link.login_method", "both")

    def _csrf(self):
        page = self.url_open("/web/login?auth_view=magic")
        return html.fromstring(page.content).xpath("//input[@name='csrf_token']")[0].get("value")

    def test_user_email_endpoint_removed(self):
        response = self.url_open("/auth/magic-link/user-email", data="{}",
                                 headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 404)

    def test_wildcard_email_does_not_match(self):
        before = self.env["auth.magic.link"].sudo().search_count([("user_id", "=", self.user.id)])
        self.url_open("/web/login", data={"csrf_token": self._csrf(), "email_login": "magic-http%",
                                          "type": "magic_link"})
        self.assertEqual(self.env["auth.magic.link"].sudo().search_count([("user_id", "=", self.user.id)]), before)
        self.url_open("/web/login", data={"csrf_token": self._csrf(), "email_login": "MAGIC-HTTP@example.invalid",
                                          "type": "magic_link"})
        self.assertEqual(self.env["auth.magic.link"].sudo().search_count([("user_id", "=", self.user.id)]), before + 1)

    def test_get_confirms_and_post_consumes(self):
        link, token = self.env["auth.magic.link"].sudo().create_login_token(
            self.user, fields.Datetime.add(fields.Datetime.now(), minutes=10))
        page = self.url_open(f"/auth/magic-login?token={token}&redirect=/\\evil.example")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Continue to sign in", page.content)
        self.assertEqual(page.headers.get("Cache-Control"), "no-store")
        self.assertFalse(link.used_at, "GET must not consume the token")
        document = html.fromstring(page.content)
        self.assertFalse(document.xpath("//input[@name='redirect']"), "unsafe redirect dropped")
        csrf = document.xpath("//input[@name='csrf_token']")[0].get("value")
        response = self.url_open("/auth/magic-login", data={"csrf_token": csrf, "token": token,
                                                            "redirect": "//evil.example"}, allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/odoo"))
        link.invalidate_recordset()
        self.assertTrue(link.used_at)
        self.url_open("/web/session/logout")
        replay = self.url_open("/auth/magic-login", data={"csrf_token": self._csrf(), "token": token},
                               allow_redirects=False)
        self.assertEqual(replay.status_code, 303)
        self.assertIn("/web/login", replay.headers["Location"])
