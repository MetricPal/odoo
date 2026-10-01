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
        self.assertIn(
            b"If an account exists for that email, a login link has been sent.",
            response.content,
        )
