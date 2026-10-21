import io
import json
from datetime import datetime
from uuid import uuid4

from PIL import Image

from odoo import tools
from odoo.modules.module import Manifest
from odoo.tests import HttpCase, TransactionCase, new_test_user
from odoo.tools import file_open

from ..constants import INLINE_LOGO_FILENAME, INLINE_LOGO_SRC


class TestMetricBranding(TransactionCase):
    def test_module_card_uses_metric_icon(self):
        manifest = Manifest.for_addon('branding')
        self.assertEqual(
            manifest['icon'],
            '/branding/static/src/img/metric_io_favicon.png',
        )

        with file_open(manifest['icon'].removeprefix('/'), mode='rb') as icon_file:
            icon = Image.open(icon_file)
            self.assertEqual(icon.format, 'PNG')
            self.assertEqual(icon.size, (256, 256))

    def test_default_company_and_website_use_metric_identity(self):
        company = self.env.ref('base.main_company')
        website = self.env.ref('base.default_website')

        self.assertEqual(company.name, 'metric.io')
        self.assertEqual(company.partner_id.name, 'metric.io')
        self.assertTrue(company.logo)
        self.assertTrue(company.logo_web)
        self.assertFalse(company.uses_default_logo)

        logo = Image.open(io.BytesIO(company.logo.content))
        self.assertEqual(logo.format, 'PNG')
        self.assertEqual(logo.size, (496, 241))
        self.assertEqual(logo.convert('RGBA').getchannel('A').getbbox(), (16, 16, 480, 225))

        for field_name in ('image_1024', 'image_512', 'image_256', 'image_128'):
            with self.subTest(field_name=field_name):
                self.assertTrue(company.partner_id[field_name])

        self.assertEqual(website.name, 'metric.io')
        self.assertEqual(website.logo.content, company.logo.content)
        self.assertTrue(website.favicon)

        favicon = Image.open(io.BytesIO(website.favicon.content))
        self.assertEqual(favicon.format, 'ICO')

    def test_web_layout_uses_metric_favicon_as_default(self):
        layout = self.env.ref('web.layout')._get_combined_arch()
        favicon_links = layout.xpath("//link[@rel='shortcut icon']")

        self.assertEqual(len(favicon_links), 1)
        self.assertEqual(
            favicon_links[0].get('t-att-href'),
            "x_icon or '/branding/static/src/img/metric_io_favicon.ico'",
        )

    def test_auth_styles_are_loaded_on_auth_pages(self):
        manifest = Manifest.for_addon('branding')

        self.assertIn(
            'branding/static/src/scss/auth.scss',
            manifest['assets']['web.assets_frontend_minimal'],
        )

    def test_auth_pages_use_metric_branding_and_oauth_first(self):
        arch = self.env.ref('auth_magic_link.standalone_login_layout')._get_combined_arch()
        logo = arch.xpath("//img[@alt='Logo']")[0]
        logo_parent = logo.getparent()
        footer = arch.xpath("//div[hasclass('o_auth_brand_footer')]")[0]
        container = arch.xpath("//div[hasclass('container') and hasclass('py-5')]")[0]
        login_card = arch.xpath("//div[contains(@t-attf-class, 'o_database_list')]")[0]
        card_body = arch.xpath("//div[hasclass('card-body')]")[0]

        self.assertIn('height:57px', logo.get('style'))
        self.assertLessEqual(
            {'min-vh-100', 'd-flex', 'flex-column'},
            set(container.get('class').split()),
        )
        self.assertIn('flex-grow-1 d-flex flex-column', login_card.get('t-attf-class'))
        self.assertLessEqual(
            {'d-flex', 'flex-column', 'flex-grow-1'},
            set(card_body.get('class').split()),
        )
        self.assertNotIn('border-bottom', logo_parent.get('class', ''))
        self.assertFalse(logo_parent.xpath("./h1"))
        self.assertNotIn('border-top', footer.get('class', ''))
        self.assertIn('mt-auto', footer.get('class').split())
        self.assertEqual(footer.get('t-if'), 'not disable_footer')
        self.assertEqual(len(footer.xpath("./span[@t-out='res_company.name']")), 1)
        self.assertIn('© 2026 .', ''.join(footer.itertext()))
        self.assertEqual(footer.xpath("normalize-space(./a[@href='/privacy'])"), 'Privacy')
        self.assertFalse(arch.xpath("//a[@href='/web/database/manager']"))
        self.assertNotIn('Powered by', ''.join(arch.itertext()))
        self.assertFalse(arch.xpath("//a[contains(@href, 'odoo.com') and contains(@href, 'utm_medium=auth')]"))

        login_arch = self.env.ref('web.login')._get_combined_arch()
        oauth_arch = self.env.ref('web.login_oauth')._get_combined_arch()
        reset_arch = self.env.ref('auth_signup.reset_password')._get_combined_arch()

        self.assertEqual(
            len(login_arch.xpath("//owl-component/preceding-sibling::t[@t-call='web.login_oauth']")),
            1,
        )
        self.assertFalse(login_arch.xpath("//h1[hasclass('visually-hidden')]"))
        self.assertEqual(
            login_arch.xpath("normalize-space(//h1[contains(@class, 'mt-2')])"),
            'Turn complexity into clarity',
        )
        self.assertEqual(
            login_arch.xpath("//h1[contains(@class, 'mt-2')]")[0].get('style'),
            'font-size:19px; font-weight:400; color:#212529;',
        )
        self.assertEqual(
            login_arch.xpath("//h1[contains(@class, 'mt-2')]")[0].get('t-if'),
            "not (message and auth_email_alert_view == 'magic')",
        )
        self.assertEqual(
            login_arch.xpath("normalize-space(//div[hasclass('o_auth_magic_link_message_heading')]/h1)"),
            'Check your email',
        )
        self.assertEqual(
            login_arch.xpath("//div[hasclass('o_auth_magic_link_message_heading')]/h1")[0].get('style'),
            'font-size:19px; font-weight:400; color:#212529;',
        )
        self.assertEqual(
            len(login_arch.xpath("//div[hasclass('o_auth_magic_link_message_heading')]/p/t[@t-out='message']")),
            1,
        )
        self.assertEqual(
            login_arch.xpath("//div[hasclass('o_auth_magic_link_message_heading')]/p")[0].get('style'),
            'font-size:14px; font-weight:400; color:#6c757d;',
        )
        self.assertEqual(
            login_arch.xpath("//div[hasclass('o_auth_magic_link_message_heading')]/p")[0].get('role'),
            'status',
        )
        self.assertEqual(
            login_arch.xpath("normalize-space(//div[hasclass('o_auth_magic_link_message_heading')]/a[@href='/web/login'])"),
            'Back to Login',
        )
        self.assertIn(
            'mx-auto',
            login_arch.xpath("//div[hasclass('o_auth_magic_link_message_heading')]/a[@href='/web/login']")[0].get('class').split(),
        )
        self.assertEqual(
            login_arch.xpath("//p[@role='status' and contains(@class, 'alert-success')]")[0].get('t-if'),
            "message and auth_email_alert_view != 'magic'",
        )
        self.assertEqual(
            login_arch.xpath("//form[contains(@t-attf-class, 'oe_login_form')]")[0].get('t-attf-class'),
            "oe_login_form #{'' if login and not (message and auth_email_alert_view == 'magic') else 'd-none'}",
        )
        self.assertEqual(
            login_arch.xpath("//owl-component")[0].get('t-if'),
            "not login and not (message and auth_email_alert_view == 'magic')",
        )
        self.assertEqual(
            login_arch.xpath("//owl-component/preceding-sibling::t[@t-call='web.login_oauth']")[0].get('t-if'),
            "not (message and auth_email_alert_view == 'magic')",
        )
        self.assertFalse(login_arch.xpath("//button[@name='redirect' and @value='/web/become']"))
        self.assertNotIn('Log in as superuser', ''.join(login_arch.itertext()))
        self.assertFalse(login_arch.xpath("//form[contains(@t-attf-class, 'oe_login_form')]//t[@t-call='web.login_oauth']"))
        self.assertNotIn('- or -', ''.join(oauth_arch.itertext()))
        self.assertEqual(
            oauth_arch.xpath("normalize-space(//div[hasclass('o_login_auth_divider')]/span[2])"),
            'Or',
        )
        self.assertEqual(
            oauth_arch.xpath("//div[hasclass('o_login_auth_divider')]")[0].get('t-if'),
            "auth_email_login_mode != 'oauth_only'",
        )
        self.assertEqual(
            len(oauth_arch.xpath("//div[hasclass('o_login_auth_divider')]/span[hasclass('border-top')]")),
            2,
        )

        self.assertFalse(reset_arch.xpath("//t[@t-call='web.login_oauth']"))
        self.assertFalse(reset_arch.xpath("//div[hasclass('o_login_auth_divider')]"))
        self.assertEqual(len(reset_arch.xpath("//h1")), 2)
        self.assertEqual(
            reset_arch.xpath("normalize-space(//div[hasclass('o_auth_reset_password_message_heading')]/h1)"),
            'Check your email',
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('o_auth_reset_password_message_heading')]/h1")[0].get('style'),
            'font-size:19px; font-weight:400; color:#212529;',
        )
        self.assertEqual(
            len(reset_arch.xpath("//div[hasclass('o_auth_reset_password_message_heading')]/p/t[@t-out='message']")),
            1,
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('o_auth_reset_password_message_heading')]/p")[0].get('style'),
            'font-size:14px; font-weight:400; color:#6c757d;',
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('o_auth_reset_password_message_heading')]/p")[0].get('role'),
            'status',
        )
        self.assertIn(
            'mx-auto',
            reset_arch.xpath("//div[hasclass('oe_login_form')]/a[@href='/web/login']")[0].get('class').split(),
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('oe_login_buttons')]/div")[0].get('class'),
            'text-center small mt-2',
        )
        self.assertEqual(
            reset_arch.xpath("normalize-space(//div[hasclass('o_auth_reset_password_heading')]/h1/t[@t-if='token and not invalid_token'])"),
            'Set your password',
        )
        self.assertEqual(
            reset_arch.xpath("normalize-space(//div[hasclass('o_auth_reset_password_heading')]/h1/t[@t-else=''])"),
            'Reset your password',
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('o_auth_reset_password_heading')]/h1")[0].get('style'),
            'font-size:19px; font-weight:400; color:#212529;',
        )
        self.assertEqual(
            reset_arch.xpath("normalize-space(//div[hasclass('o_auth_reset_password_heading')]/p/t[@t-if='token and not invalid_token'])"),
            'Create a password to secure your account.',
        )
        self.assertEqual(
            reset_arch.xpath("normalize-space(//div[hasclass('o_auth_reset_password_heading')]/p/t[@t-else=''])"),
            "Forgot your password? Let's fix that. Enter your email below.",
        )
        self.assertEqual(
            reset_arch.xpath("//div[hasclass('o_auth_reset_password_heading')]/p")[0].get('style'),
            'font-size:14px; font-weight:400; color:#6c757d;',
        )

    def test_powered_by_odoo_is_removed_from_shared_views(self):
        view_xmlids = (
            'web.brand_promotion_message',
            'web.brand_promotion',
            'web.login_layout',
            'portal.portal_record_sidebar',
            'mail.mail_notification_layout',
            'mail.mail_notification_layout_with_responsible_signature',
            'mail.mail_notification_invite',
            'mail.mail_notification_light',
        )
        for view_xmlid in view_xmlids:
            with self.subTest(view_xmlid=view_xmlid):
                arch = self.env.ref(view_xmlid)._get_combined_arch()
                self.assertNotIn('Powered by', ''.join(arch.itertext()))
                self.assertFalse(
                    arch.xpath("//a[contains(@href, 'odoo.com') and contains(@href, 'utm_medium')]")
                )

        for view_xmlid in (
            'mail.mail_notification_layout',
            'mail.mail_notification_invite',
            'mail.mail_notification_light',
        ):
            with self.subTest(unfollow_view_xmlid=view_xmlid):
                arch = self.env.ref(view_xmlid)._get_combined_arch()
                self.assertEqual(len(arch.xpath("//a[@href='/mail/unfollow']")), 1)

        notification_arch = self.env.ref('mail.mail_notification_layout')._get_combined_arch()
        self.assertEqual(len(notification_arch.xpath("//table[@data-branding-content-shell='1']")), 1)
        self.assertEqual(len(notification_arch.xpath("//td[@data-branding-content-cell='1']")), 1)
        self.assertIn(
            'padding:24px 28px',
            notification_arch.xpath("//td[@data-branding-content-cell='1']")[0].get('style'),
        )
        self.assertFalse(
            notification_arch.xpath("//div[@t-if='show_footer' and contains(@style, 'height:32px')]")
        )

    def test_digest_footer_has_no_odoo_promotion(self):
        arch = self.env.ref('digest.digest_mail_main')._get_combined_arch()

        self.assertNotIn('Powered by', ''.join(arch.itertext()))
        self.assertFalse(arch.xpath("//p[@id='powered']"))
        self.assertFalse(arch.xpath("//p[hasclass('company_name')]"))
        self.assertFalse(arch.xpath("//tr[@t-if='display_mobile_banner']"))
        self.assertFalse(arch.xpath("//div[@id='footer']"))
        self.assertEqual(len(arch.xpath("//t[@t-call='branding.branding_mail_footer']")), 1)
        self.assertEqual(arch.xpath("//td[@height='32']")[0].get('height'), '32')
        by_odoo = arch.xpath("//div[hasclass('by_odoo')]")
        self.assertEqual(len(by_odoo), 1)
        self.assertIn('display:none', by_odoo[0].get('style'))
        self.assertEqual(
            arch.xpath('(//table)[1]')[0].get('data-branding-email-kind'),
            'digest',
        )
        header = arch.xpath("//table[@id='header']")[0]
        content = arch.xpath("//table[hasclass('global_layout') and not(@id='header')]")[0]
        self.assertIn('border-radius: 12px 12px 0 0', header.get('style'))
        self.assertIn('border-radius: 0 0 12px 12px', content.get('style'))
        self.assertIn('border-collapse: separate', header.get('style'))
        self.assertIn('border-collapse: separate', content.get('style'))
        self.assertEqual(header.get('width'), '656')
        self.assertEqual(content.get('width'), '656')
        self.assertIn('width:656px', header.get('style'))
        self.assertIn('width:656px', content.get('style'))
        self.assertIn('border-top:1px solid #eeeeee', header.get('style'))
        self.assertIn('border-left:1px solid #eeeeee', header.get('style'))
        self.assertIn('border-right:1px solid #eeeeee', header.get('style'))
        self.assertIn('border-left:1px solid #eeeeee', content.get('style'))
        self.assertIn('border-right:1px solid #eeeeee', content.get('style'))
        self.assertIn('border-bottom:1px solid #eeeeee', content.get('style'))
        self.assertIn('padding: 24px 28px 5px 28px', header.xpath(".//td[hasclass('p0')][1]")[0].get('style'))
        self.assertIn('padding: 24px 28px 0px 28px', content.xpath(".//td[hasclass('global_td')]")[0].get('style'))

    def test_rendered_digest_email_contains_shared_brand_footer(self):
        digest = self.env.ref('digest.digest_digest_default')
        user = self.env.ref('base.user_admin')
        unsubscribe_token = digest._get_unsubscribe_token(user.id)

        rendered_body = self.env['mail.render.mixin']._render_template(
            'digest.digest_mail_main',
            'digest.digest',
            digest.ids,
            engine='qweb_view',
            add_context={
                'title': digest.name,
                'top_button_label': 'Connect',
                'top_button_url': digest.get_base_url(),
                'company': user.company_id,
                'user': user,
                'unsubscribe_token': unsubscribe_token,
                'tips_count': 1,
                'formatted_date': tools.format_date(self.env, datetime.today(), date_format='MMMM dd, yyyy'),
                'display_mobile_banner': True,
                'kpi_data': digest._compute_kpis(user.company_id, user),
                'tips': digest._compute_tips(user.company_id, user, tips_count=1, consumed=False),
                'preferences': digest._compute_preferences(user.company_id, user),
            },
            options={
                'preserve_comments': True,
                'post_process': True,
            },
        )[digest.id]
        full_mail = self.env['mail.render.mixin']._render_encapsulate(
            'digest.digest_mail_layout',
            rendered_body,
            add_context={
                'company': user.company_id,
                'user': user,
            },
        )

        self.assertEqual(full_mail.count('data-branding-mail-footer="1"'), 1)
        self.assertIn('width="656"', full_mail)
        self.assertIn('width:656px', full_mail)
        self.assertIn('padding: 24px 28px 0px 28px', full_mail)
        self.assertIn('border-left:1px solid #eeeeee', full_mail)
        self.assertIn('border-right:1px solid #eeeeee', full_mail)
        self.assertIn('height:32px; line-height:32px', full_mail)
        self.assertIn('metric.io', full_mail)
        self.assertIn('/digest/%s/unsubscribe' % digest.id, full_mail)

    def test_light_mail_has_white_canvas_and_no_header_logo_or_legacy_footer(self):
        arch = self.env.ref('mail.mail_notification_light')._get_combined_arch()

        self.assertFalse(arch.xpath("//img[contains(@t-att-src, '/logo.png?company=')]"))
        self.assertFalse(arch.xpath("//td[b[@t-out='company.name']]"))
        self.assertIn('background-color: #ffffff', arch.xpath('//body/table[1]')[0].get('style'))

    def _installed_mail_template_xmlids(self):
        templates = self.env['mail.template'].sudo().search([])
        return {
            xmlid
            for xmlid in templates.get_external_id().values()
            if xmlid and not xmlid.startswith('__export__.')
        }

    def test_branding_layout_has_single_centered_600px_content_area(self):
        arch = self.env.ref('branding.branding_mail_layout')._get_combined_arch()
        footer_arch = self.env.ref('branding.branding_mail_footer')._get_combined_arch()

        self.assertEqual(len(arch.xpath("//table[@data-branding-body-canvas='1']")), 1)
        self.assertEqual(len(arch.xpath("//table[@data-branding-content-shell='1']")), 1)
        self.assertEqual(len(arch.xpath("//t[@t-call='branding.branding_mail_footer']")), 1)
        self.assertEqual(len(footer_arch.xpath("//table[@data-branding-mail-footer='1']")), 1)
        self.assertEqual(arch.xpath("//table[@data-branding-content-shell='1']")[0].get('width'), '656')
        self.assertEqual(footer_arch.xpath("//table[@data-branding-mail-footer='1']")[0].get('width'), '656')
        self.assertIn('padding:32px 0', arch.xpath("//table[@data-branding-body-canvas='1']")[0].get('style'))
        self.assertIn('max-width:656px', arch.xpath("//table[@data-branding-content-shell='1']")[0].get('style'))
        self.assertIn('max-width:656px', footer_arch.xpath("//table[@data-branding-mail-footer='1']")[0].get('style'))
        self.assertIn('background-color:#EEEEEE', footer_arch.xpath("//table[@data-branding-mail-footer='1']")[0].get('style'))
        self.assertIn('padding:24px 28px', arch.xpath("//table[@data-branding-content-shell='1']//td")[0].get('style'))
        self.assertIn('padding:24px 28px', footer_arch.xpath("//table[@data-branding-mail-footer='1']//td")[0].get('style'))
        self.assertEqual(arch.xpath("//td[@height='32']")[0].get('height'), '32')

    def test_branding_template_override_records_cover_installed_templates(self):
        overrides = self.env['branding.mail.template.override'].sudo().search([])
        installed_xmlids = self._installed_mail_template_xmlids()
        override_xmlids = set(overrides.mapped('xmlid'))

        self.assertTrue(installed_xmlids)
        self.assertLessEqual(installed_xmlids, override_xmlids)
        for override in overrides:
            with self.subTest(xmlid=override.xmlid):
                body = override.body_html or ''
                self.assertEqual(override.email_layout_xmlid, 'branding.branding_mail_layout')
                self.assertNotIn('Sent by', body)
                self.assertNotIn('Powered by', body)
                self.assertNotIn('/logo.png?company=', body)
                self.assertNotIn('width="590"', body)
                self.assertNotIn("width='590'", body)
                self.assertNotIn('min-width: 590px', body)
                self.assertNotIn('min-width:590px', body)

    def test_installed_templates_use_branding_layout_and_clean_bodies(self):
        for xmlid in self._installed_mail_template_xmlids():
            with self.subTest(xmlid=xmlid):
                template = self.env.ref(xmlid)
                body = template.body_html or ''
                self.assertEqual(template.email_layout_xmlid, 'branding.branding_mail_layout')
                self.assertFalse(template.email_layout_force_header)
                self.assertFalse(template.email_layout_force_footer)
                self.assertNotIn('Sent by', body)
                self.assertNotIn('Powered by', body)
                self.assertNotIn('/logo.png?company=', body)
                self.assertNotIn('width="590"', body)
                self.assertNotIn('min-width', body)

    def test_template_email_gets_standard_branding_layout(self):
        partner = self.env['res.partner'].create({
            'name': 'Template Recipient',
            'email': 'recipient@example.invalid',
        })
        template = self.env['mail.template'].create({
            'name': 'Branding footer send template',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'subject': 'Branding footer send template',
            'body_html': '<p>Hello <t t-out="object.name"/></p>',
            'email_to': '{{ object.email }}',
            'email_layout_xmlid': 'branding.branding_mail_layout',
            'email_layout_force_footer': False,
        })

        mail = self.env['mail.mail'].browse(template.send_mail(partner.id))
        outgoing_values = mail._prepare_outgoing_list()[0]

        self.assertIn('Hello Template Recipient', outgoing_values['body'])
        self.assertEqual(outgoing_values['body'].count('data-branding-mail-footer="1"'), 1)
        self.assertEqual(outgoing_values['body'].count('data-branding-content-shell="1"'), 1)
        self.assertIn('width="656"', outgoing_values['body'])
        self.assertIn('padding:32px 0', outgoing_values['body'])
        self.assertIn('height:32px; line-height:32px', outgoing_values['body'])
        self.assertIn('padding:24px 28px', outgoing_values['body'])
        self.assertIn('data-branding-company-name="1"', outgoing_values['body'])
        self.assertNotIn('Powered by', outgoing_values['body'])
        self.assertNotIn('odoo.com?utm_source=db', outgoing_values['body'])
        self.assertIn(INLINE_LOGO_SRC, outgoing_values['body'])
        self.assertTrue(
            any(attachment[0] == INLINE_LOGO_FILENAME for attachment in outgoing_values['attachments'])
        )

    def test_reset_password_layout_gets_shared_branding_footer(self):
        user = self.env.ref('base.user_admin')
        body = self.env['mail.render.mixin']._render_template(
            self.env.ref('auth_signup.reset_password_email'),
            model='res.users',
            res_ids=user.ids,
            engine='qweb_view',
            options={'post_process': True},
        )[user.id]
        body_html = self.env['mail.render.mixin']._render_encapsulate(
            'mail.mail_notification_layout',
            body,
            context_record=user,
            add_context={
                'email_add_signature': True,
                'email_notification_force_header': True,
                'email_notification_force_footer': True,
                'signature': self.env.user.signature,
                'subtitles': ['Your Account', user.display_name],
            },
        )

        self.assertIn('A password reset was requested', body_html)
        self.assertEqual(body_html.count('data-branding-mail-footer="1"'), 1)
        self.assertEqual(body_html.count('data-branding-content-shell="1"'), 1)
        self.assertEqual(body_html.count('data-branding-content-cell="1"'), 1)
        self.assertIn('max-width:656px', body_html)
        self.assertIn('width="656"', body_html)
        self.assertIn('padding:24px 28px', body_html)
        self.assertNotIn('height:32px; line-height:32px', body_html)
        self.assertIn(INLINE_LOGO_SRC, body_html)
        self.assertNotIn('width="590"', body_html)
        self.assertNotIn('Powered by', body_html)

    def test_direct_outgoing_email_gets_standard_branding_layout(self):
        mail = self.env['mail.mail'].create({
            'body_html': '<p>Notification</p>',
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Notification',
        })

        outgoing_values = mail._prepare_outgoing_list()[0]

        self.assertIn('Notification', outgoing_values['body'])
        self.assertEqual(outgoing_values['body'].count('data-branding-mail-footer="1"'), 1)
        self.assertEqual(outgoing_values['body'].count('data-branding-content-shell="1"'), 1)
        self.assertIn('width="656"', outgoing_values['body'])
        self.assertIn('max-width:656px', outgoing_values['body'])
        self.assertIn('background-color:#EEEEEE', outgoing_values['body'])
        self.assertIn(INLINE_LOGO_SRC, outgoing_values['body'])
        self.assertTrue(
            any(attachment[0] == INLINE_LOGO_FILENAME for attachment in outgoing_values['attachments'])
        )

    def test_already_branded_outgoing_email_is_not_wrapped_twice(self):
        branded_body = self.env['mail.render.mixin']._render_encapsulate(
            'branding.branding_mail_layout',
            '<p>Already branded</p>',
            add_context={'company': self.env.company},
        )
        mail = self.env['mail.mail'].create({
            'body_html': branded_body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Already branded',
        })

        outgoing_values = mail._prepare_outgoing_list()[0]

        self.assertIn('Already branded', outgoing_values['body'])
        self.assertEqual(outgoing_values['body'].count('data-branding-mail-footer="1"'), 1)
        self.assertEqual(outgoing_values['body'].count('data-branding-content-shell="1"'), 1)

    def test_inline_brand_logo_is_related_mime_part_not_attachment(self):
        mail = self.env['mail.mail'].create({
            'body_html': f'<p>Notification</p><img src="{INLINE_LOGO_SRC}"/>',
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Notification',
        })
        outgoing_values = mail._prepare_outgoing_list()[0]
        message = self.env['ir.mail_server']._build_email__(
            email_from=outgoing_values['email_from'],
            email_to=outgoing_values['email_to'],
            subject=outgoing_values['subject'],
            body=outgoing_values['body'],
            body_alternative=outgoing_values['body_alternative'],
            email_cc=outgoing_values['email_cc'],
            reply_to=outgoing_values['reply_to'],
            attachments=outgoing_values['attachments'],
            message_id=outgoing_values['message_id'],
            references=outgoing_values['references'],
            object_id=outgoing_values['object_id'],
            subtype='html',
            subtype_alternative='plain',
            headers=outgoing_values['headers'],
        )
        logo_parts = [
            part for part in message.walk()
            if part.get('Content-ID') == '<metric-io-logo@branding>'
        ]

        self.assertEqual(len(logo_parts), 1)
        self.assertEqual(logo_parts[0].get_content_disposition(), 'inline')
        self.assertFalse(
            any(
                part.get_filename() == 'metric_io_logo.png'
                and part.get_content_disposition() == 'attachment'
                for part in message.walk()
            )
        )


    def test_override_waits_until_template_model_is_loaded(self):
        """Branding can load before the app owning a template during an upgrade."""
        from unittest.mock import patch

        from odoo.orm.registry import Registry

        template = self.env['mail.template'].create({
            'name': 'Pending template', 'model_id': self.env.ref('base.model_res_partner').id,
            'body_html': '<p>Original</p>',
        })
        self.env['ir.model.data'].create({
            'module': 'branding_test', 'name': 'pending_template',
            'model': 'mail.template', 'res_id': template.id,
        })
        override = self.env['branding.mail.template.override'].create({
            'xmlid': 'branding_test.pending_template', 'template_name': 'Branded template',
            'body_html': '<p>Branded</p>',
        })
        contains = Registry.__contains__
        with patch.object(Registry, '__contains__',
                          lambda registry, name: name != 'res.partner' and contains(registry, name)):
            self.assertFalse(override._apply())
        self.assertFalse(override.applied_checksum)
        self.assertEqual(template.name, 'Pending template')

        # Once every module is loaded the register hook applies it.
        override._register_hook()
        self.assertTrue(override.applied_checksum)
        self.assertEqual(template.name, 'Branded template')
        self.assertIn('Branded', template.body_html)


class TestBrandingSessionInfo(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "branding-session-test"
        cls.user = new_test_user(
            cls.env,
            login="branding-session-user",
            email="branding-session@example.invalid",
            password=cls.password,
            groups="base.group_user",
        )

    def test_session_info_exposes_current_user_email(self):
        self.authenticate(self.user.login, self.password)
        self.env["res.users.settings"]._find_or_create_for_user(self.user)
        response = self.url_open(
            "/web/session/get_session_info",
            data=json.dumps({
                "jsonrpc": "2.0",
                "method": "call",
                "id": str(uuid4()),
            }),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["result"]["user_email"],
            "branding-session@example.invalid",
        )
