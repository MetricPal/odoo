import io
import json
from uuid import uuid4

from PIL import Image

from odoo.modules.module import Manifest
from odoo.tests import HttpCase, TransactionCase, new_test_user
from odoo.tools import file_open

from ..constants import INLINE_LOGO_CID, INLINE_LOGO_FILENAME, INLINE_LOGO_SRC


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

    def test_digest_footer_has_no_odoo_promotion(self):
        arch = self.env.ref('digest.digest_mail_main')._get_combined_arch()

        self.assertNotIn('Powered by', ''.join(arch.itertext()))
        self.assertFalse(arch.xpath("//p[@id='powered']"))
        self.assertFalse(arch.xpath("//p[hasclass('company_name')]"))
        self.assertFalse(arch.xpath("//tr[@t-if='display_mobile_banner']"))
        self.assertFalse(arch.xpath("//div[@id='footer']"))
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

    def test_light_mail_has_white_canvas_and_no_header_logo_or_legacy_footer(self):
        arch = self.env.ref('mail.mail_notification_light')._get_combined_arch()

        self.assertFalse(arch.xpath("//img[contains(@t-att-src, '/logo.png?company=')]"))
        self.assertFalse(arch.xpath("//td[b[@t-out='company.name']]"))
        self.assertIn('background-color: #ffffff', arch.xpath('//body/table[1]')[0].get('style'))

    def test_all_outgoing_email_gets_shared_brand_footer(self):
        company = self.env.ref('base.main_company')
        company.street = 'Example Street 10'
        company.street2 = False
        company.zip = False
        company.city = 'Kuala Lumpur'
        company.state_id = False
        company.country_id = self.env.ref('base.my')
        company.email_body_background_color = '#F7F8FA'
        company.email_content_background_color = '#FFFFFF'
        company.email_footer_background_color = '#EEEEEE'

        mail = self.env['mail.mail'].create({
            'body_html': '<html><body><p>Security notification</p></body></html>',
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Security notification',
            'record_company_id': company.id,
        })
        outgoing_values = mail._prepare_outgoing_list()[0]
        inline_attachment = next(
            attachment
            for attachment in outgoing_values['attachments']
            if attachment[0] == INLINE_LOGO_FILENAME
        )

        self.assertEqual(outgoing_values['body'].count('data-branding-mail-footer="1"'), 1)
        self.assertIn('data-branding-footer-align="center"', outgoing_values['body'])
        self.assertIn('align="center" style="padding:0; text-align:center;"', outgoing_values['body'])
        self.assertIn('td dir="ltr" align="left"', outgoing_values['body'])
        self.assertIn('width="590"', outgoing_values['body'])
        self.assertIn('max-width:590px', outgoing_values['body'])
        self.assertIn('background-color:#EEEEEE', outgoing_values['body'])
        self.assertIn(f'src="{INLINE_LOGO_SRC}"', outgoing_values['body'])
        self.assertIn('width="64"', outgoing_values['body'])
        self.assertIn('data-branding-company-name="1"', outgoing_values['body'])
        self.assertIn('<span>metric</span><span>.</span><span>io</span>', outgoing_values['body'])
        self.assertIn('Example Street 10', outgoing_values['body'])
        self.assertIn('Kuala Lumpur, Malaysia', outgoing_values['body'])
        self.assertIn('>Privacy</a>', outgoing_values['body'])
        self.assertIn('data-branding-copyright="1"', outgoing_values['body'])
        self.assertIn('&copy;', outgoing_values['body'])
        self.assertIn('background-color:#F7F8FA !important', outgoing_values['body'])
        self.assertEqual(inline_attachment[1], company.logo_web.content)
        self.assertEqual(inline_attachment[2], 'image/png')

    def test_email_branding_colors_are_company_settings(self):
        company = self.env.ref('base.main_company')
        company.write({
            'email_body_background_color': '#123456',
            'email_content_background_color': '#abcdef',
            'email_footer_background_color': '#654321',
        })
        settings = self.env['res.config.settings'].create({
            'company_id': company.id,
        })

        self.assertEqual(settings.email_body_background_color, '#123456')
        self.assertEqual(settings.email_content_background_color, '#abcdef')
        self.assertEqual(settings.email_footer_background_color, '#654321')

        settings.write({
            'email_body_background_color': '#112233',
            'email_content_background_color': '#445566',
            'email_footer_background_color': '#778899',
        })
        settings.execute()

        self.assertEqual(company.email_body_background_color, '#112233')
        self.assertEqual(company.email_content_background_color, '#445566')
        self.assertEqual(company.email_footer_background_color, '#778899')

    def test_email_surfaces_use_company_colors_and_content_border_style(self):
        company = self.env.ref('base.main_company')
        company.write({
            'email_body_background_color': '#123456',
            'email_content_background_color': '#abcdef',
            'email_footer_background_color': '#654321',
        })
        mail = self.env['mail.mail'].create({
            'body_html': (
                '<table style="width:100%; background-color:#F1F1F1;">'
                '<tr><td align="center">'
                '<table width="590" style="background-color:#ffffff; '
                'border:1px solid #d8dadd; border-collapse:collapse;">'
                '<tr><td>Bordered content</td></tr>'
                '</table>'
                '</td></tr></table>'
            ),
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Custom colors',
            'record_company_id': company.id,
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('background-color:#123456', body)
        self.assertIn('bgcolor="#123456"', body)
        self.assertIn('background-color:#abcdef', body)
        self.assertIn('border:1px solid #eeeeee', body)
        self.assertIn('border-radius:12px', body)
        self.assertIn('background-color:#654321', body)
        self.assertIn('width="590"', body)
        self.assertNotIn('width="600"', body)

    def test_new_mail_templates_force_standard_footer_by_default(self):
        template = self.env['mail.template'].create({
            'name': 'Branding footer template',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'subject': 'Branding footer template',
            'body_html': '<p>Hello <t t-out="object.name"/></p>',
            'email_to': '{{ object.email }}',
            'email_layout_xmlid': 'mail.mail_notification_light',
        })

        self.assertTrue(template.email_layout_force_footer)

    def test_template_email_gets_standard_footer_even_when_template_footer_is_disabled(self):
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
            'email_layout_xmlid': 'mail.mail_notification_light',
            'email_layout_force_footer': False,
        })

        mail = self.env['mail.mail'].browse(template.send_mail(partner.id))
        outgoing_values = mail._prepare_outgoing_list()[0]

        self.assertIn('Hello Template Recipient', outgoing_values['body'])
        self.assertEqual(outgoing_values['body'].count('data-branding-mail-footer="1"'), 1)
        self.assertIn('data-branding-company-name="1"', outgoing_values['body'])
        self.assertNotIn('Powered by', outgoing_values['body'])
        self.assertNotIn('odoo.com?utm_source=db', outgoing_values['body'])

    def test_outgoing_email_removes_template_powered_by_odoo_promotion(self):
        mail = self.env['mail.mail'].create({
            'body_html': (
                '<html><body>'
                '<p>Expense notification</p>'
                '<p style="text-align:center;">Powered by '
                '<a target="_blank" href="https://www.odoo.com?utm_source=db&amp;utm_medium=expense">'
                'Odoo</a>.</p>'
                '</body></html>'
            ),
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Expense notification',
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('Expense notification', body)
        self.assertNotIn('Powered by', body)
        self.assertNotIn('utm_medium=expense', body)
        self.assertEqual(body.count('data-branding-mail-footer="1"'), 1)

    def test_outgoing_email_removes_template_sent_by_brand_promotion(self):
        mail = self.env['mail.mail'].create({
            'body_html': (
                '<table style="padding-top:16px; background-color:#F1F1F1; width:100%;">'
                '<tr><td align="center">'
                '<table width="590" style="background-color:white;"><tr><td>'
                '<p>Event confirmation</p>'
                '</td></tr></table>'
                '</td></tr>'
                '<!-- FOOTER BY -->'
                '<tr><td align="center" style="min-width:590px;">'
                '<table width="590" style="background-color:#F1F1F1;">'
                '<tr><td style="text-align:center;">Sent by '
                '<a target="_blank" href="https://metric.io" style="color:#875A7B;">'
                'metric.io</a><br/>Discover '
                '<a href="/event" style="color:#875A7B;">all our events</a>.'
                '</td></tr></table>'
                '</td></tr>'
                '</table>'
            ),
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Event confirmation',
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('Event confirmation', body)
        self.assertNotIn('Sent by', body)
        self.assertNotIn('Discover', body)
        self.assertNotIn('https://metric.io', body)
        self.assertEqual(body.count('data-branding-mail-footer="1"'), 1)
        self.assertLess(
            body.index('data-branding-mail-footer="1"'),
            body.rindex('</table>'),
        )
        self.assertIn('bgcolor="#F7F8FA"', body)
        self.assertIn('data-branding-footer-align="center"', body)
        self.assertIn('td dir="ltr" align="left"', body)
        self.assertNotIn('border:1px solid #eeeeee', body.split('data-branding-mail-footer="1"')[0])
        self.assertNotIn('border-radius:12px', body.split('data-branding-mail-footer="1"')[0])

    def test_magic_link_style_email_is_centered_without_legacy_company_footer(self):
        company = self.env.ref('base.main_company')
        mail = self.env['mail.mail'].create({
            'body_html': (
                '<table border="0" cellpadding="0" cellspacing="0" '
                'style="padding-top:16px; background-color:#FFFFFF; width:100%;">'
                '<tr><td align="left">'
                '<table border="0" cellpadding="0" cellspacing="0" width="590" align="left" '
                'style="padding:16px; background-color:#FFFFFF;">'
                '<tbody>'
                '<tr><td align="left" style="min-width:590px;">'
                '<table border="0" cellpadding="0" cellspacing="0" width="590" '
                'style="min-width:590px; background-color:white; padding:0px 8px;">'
                '<tr><td><span style="font-size:10px;">Your Account</span><br/>'
                '<span style="font-size:20px; font-weight:bold;">Administrator</span></td></tr>'
                '<tr><td><hr width="100%" style="margin:16px 0px;"/></td></tr>'
                '</table>'
                '</td></tr>'
                '<tr><td align="left" style="min-width:590px;">'
                '<table border="0" cellpadding="0" cellspacing="0" width="590" '
                'style="min-width:590px; background-color:white; padding:0px 8px;">'
                '<tr><td valign="top" style="font-size:13px;">'
                'A sign-in link was requested for the account linked to this email.'
                '<div style="margin:16px 0px;"><a href="/auth/magic-login?token=test" '
                'style="background-color:#875A7B; padding:8px 16px; text-decoration:none; '
                'color:#FFFFFF; border-radius:5px; font-size:13px;">Sign in</a></div>'
                '</td></tr>'
                '<tr><td style="text-align:left;"><hr width="100%" style="margin:16px 0px;"/></td></tr>'
                '</table>'
                '</td></tr>'
                '<tr><td align="left" style="min-width:590px;">'
                '<table border="0" cellpadding="0" cellspacing="0" width="590" '
                'style="min-width:590px; background-color:white; font-size:11px; padding:0px 8px;">'
                '<tr><td valign="middle" align="left">metric.io</td></tr>'
                '<tr><td valign="middle" align="left" style="opacity:0.7;">'
                '<a href="https://metric.io">https://metric.io</a>'
                '</td></tr>'
                '</table>'
                '</td></tr>'
                '</tbody>'
                '</table>'
                '</td></tr>'
                '</table>'
            ),
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Sign in to metric.io',
            'record_company_id': company.id,
        })

        body = mail._prepare_outgoing_list()[0]['body']
        content = body.split('data-branding-mail-footer="1"')[0]

        self.assertIn('A sign-in link was requested', body)
        self.assertIn('Sign in', body)
        self.assertEqual(body.count('data-branding-mail-footer="1"'), 1)
        self.assertIn('width="590" align="center"', content)
        self.assertNotIn('width="590" align="left"', content)
        self.assertNotIn('background-color:#FFFFFF', content)
        self.assertNotIn('background-color:white', content)
        self.assertEqual(content.count('<hr'), 1)
        self.assertNotIn('valign="middle" align="left">metric.io', body)
        self.assertIn('<span>metric</span><span>.</span><span>io</span>', body)

    def test_outgoing_header_company_logo_is_removed(self):
        company = self.env.ref('base.main_company')
        mail = self.env['mail.mail'].create({
            'body_html': (
                '<html><body>'
                f'<img src="/logo.png?company={company.id}" alt="Header logo"/>'
                '<p>Notification</p>'
                '</body></html>'
            ),
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Notification',
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertNotIn('/logo.png?company=', body)
        self.assertEqual(body.count(f'src="{INLINE_LOGO_SRC}"'), 1)

    def test_newsletter_footer_stays_inside_colored_centered_canvas(self):
        if 'mailing_id' not in self.env['mail.mail']._fields:
            self.skipTest('Email Marketing is not installed')

        newsletter_body = (
            '<html><body>'
            '<div style="background-color:#e9f4ff; padding:32px 20px;">'
            '<table role="presentation" align="center" width="600" '
            'style="background-color:#ffffff;"><tr><td>Newsletter</td></tr></table>'
            '</div>'
            '</body></html>'
        )
        mailing = self.env['mailing.mailing'].create({
            'subject': 'Footer design preview',
            'email_from': 'no-reply@metric.io',
            'body_arch': newsletter_body,
            'body_html': newsletter_body,
        })
        mail = self.env['mail.mail'].create({
            'body_html': newsletter_body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Footer design preview',
            'mailing_id': mailing.id,
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('data-branding-footer-align="center"', body)
        self.assertIn('align="center" border="0"', body)
        self.assertIn('td dir="ltr" align="left"', body)
        self.assertIn('bgcolor="#F7F8FA"', body)
        self.assertIn('background-color:#F7F8FA', body)
        self.assertIn('width="590"', body)
        self.assertNotIn('width="600"', body)
        self.assertIn('Privacy</a> &middot; ', body)
        self.assertIn('>Unsubscribe</a>', body)
        self.assertIn('/unsubscribe_from_list', body)
        self.assertNotIn('background-color:#ffffff !important', body)

    def test_rtl_email_footer_uses_reading_start_alignment(self):
        mail = self.env['mail.mail'].create({
            'body_html': '<html lang="fa"><body dir="rtl"><p>سلام</p></body></html>',
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'RTL notification',
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('data-branding-footer-align="right"', body)
        self.assertIn('align="right" style="padding:0; text-align:right;"', body)
        self.assertIn('td dir="rtl" align="right"', body)
        self.assertIn('margin:0 0 12px auto', body)

    def test_digest_unsubscribe_is_moved_to_shared_footer(self):
        digest_body = (
            '<html><body data-branding-email-kind="digest" '
            'style="background-color:#F9FAFB;">'
            '<div class="by_odoo" style="display:none;">'
            '<a href="http://localhost:8069/digest/1/unsubscribe?token=test&amp;user_id=2">'
            'Unsubscribe</a></div>'
            '<p>Digest content</p>'
            '</body></html>'
        )
        mail = self.env['mail.mail'].create({
            'body_html': digest_body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Periodic Digest',
        })

        body = mail._prepare_outgoing_list()[0]['body']

        self.assertIn('bgcolor="#F7F8FA"', body)
        self.assertIn('<body data-branding-email-kind="digest" style="background-color:#F7F8FA;" bgcolor="#F7F8FA">', body)
        self.assertIn('Privacy</a> &middot; ', body)
        self.assertIn('>Unsubscribe</a>', body)
        self.assertIn('token=test&amp;user_id=2', body)
        self.assertNotIn('background-color:#ffffff !important', body)

    def _render_reset_password_email(self):
        user = self.env.ref('base.user_admin')
        body = self.env['mail.render.mixin']._render_template(
            self.env.ref('auth_signup.reset_password_email'),
            model='res.users',
            res_ids=user.ids,
            engine='qweb_view',
            options={'post_process': True},
        )[user.id]
        return self.env['mail.render.mixin']._render_encapsulate(
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

    def test_reset_password_email_has_content_without_odoo_promotion(self):
        body = self._render_reset_password_email()

        self.assertIn('A password reset was requested', body)
        self.assertIn('Change password', body)
        self.assertIn('/web/reset_password?', body)
        self.assertNotIn('Powered by', body)
        self.assertNotIn('utm_medium=email', body)

    def test_reset_password_outgoing_email_keeps_rendered_content(self):
        body = self._render_reset_password_email()
        mail = self.env['mail.mail'].create({
            'body_html': body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Reset your password',
        })

        outgoing_values = mail._prepare_outgoing_list()[0]
        self.assertIn('A password reset was requested', outgoing_values['body'])
        self.assertIn('Change password', outgoing_values['body'])
        self.assertIn(
            'max-width: 590px; width: 100%; margin: 0 auto; padding: 24px 24px 0; box-sizing: border-box;',
            outgoing_values['body'],
        )
        self.assertIn('data-branding-content-align="center"', outgoing_values['body'])
        self.assertIn('data-branding-footer-align="center"', outgoing_values['body'])
        self.assertNotIn('border:1px solid #eeeeee', outgoing_values['body'])
        self.assertNotIn(
            'border-radius:12px',
            outgoing_values['body'].split('data-branding-mail-footer="1"')[0],
        )
        self.assertIn('margin-top:0; margin-bottom:32px;', outgoing_values['body'])
        self.assertIn('padding-bottom:32px', outgoing_values['body'])


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
