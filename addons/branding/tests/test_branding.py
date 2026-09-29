import base64
import io

from PIL import Image

from odoo.modules.module import Manifest
from odoo.tests import TransactionCase
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
        website = self.env.ref('website.default_website')

        self.assertEqual(company.name, 'metric.io')
        self.assertEqual(company.partner_id.name, 'metric.io')
        self.assertTrue(company.logo)
        self.assertTrue(company.logo_web)
        self.assertFalse(company.uses_default_logo)

        logo = Image.open(io.BytesIO(base64.b64decode(company.logo)))
        self.assertEqual(logo.format, 'PNG')
        self.assertEqual(logo.size, (496, 241))
        self.assertEqual(logo.convert('RGBA').getchannel('A').getbbox(), (16, 16, 480, 225))

        for field_name in ('image_1024', 'image_512', 'image_256', 'image_128'):
            with self.subTest(field_name=field_name):
                self.assertTrue(company.partner_id[field_name])

        self.assertEqual(website.name, 'metric.io')
        self.assertEqual(website.logo, company.logo)
        self.assertTrue(website.favicon)

        favicon = Image.open(io.BytesIO(base64.b64decode(website.favicon)))
        self.assertEqual(favicon.format, 'ICO')
        self.assertEqual(favicon.size, (256, 256))

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
        self.assertEqual(
            len(arch.xpath("//span[normalize-space()='Unsubscribe']")),
            2,
        )

    def test_light_mail_footer_is_left_aligned(self):
        arch = self.env.ref('mail.mail_notification_light')._get_combined_arch()
        footer_cells = arch.xpath("//td[b[@t-out='company.name']]")

        self.assertEqual(len(footer_cells), 1)
        self.assertEqual(footer_cells[0].get('align'), 'left')

    def test_outgoing_company_logo_is_embedded_by_content_id(self):
        company = self.env.ref('base.main_company')
        body = self.env['mail.render.mixin']._render_encapsulate(
            'mail.mail_notification_light',
            '<p>Security notification</p>',
            add_context={'model_description': 'Account'},
            context_record=self.env.ref('base.user_admin'),
        )
        self.assertIn(f'/logo.png?company={company.id}', body)

        mail = self.env['mail.mail'].create({
            'body_html': body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Security notification',
        })
        outgoing_values = mail._prepare_outgoing_list()[0]
        inline_attachment = next(
            attachment
            for attachment in outgoing_values['attachments']
            if attachment[0] == INLINE_LOGO_FILENAME
        )

        self.assertIn(f'src="{INLINE_LOGO_SRC}"', outgoing_values['body'])
        self.assertNotIn('/logo.png?company=', outgoing_values['body'])
        self.assertEqual(inline_attachment[1], base64.b64decode(company.logo_web))
        self.assertEqual(inline_attachment[2], 'image/png')

    def _render_reset_password_email(self):
        user = self.env.ref('base.user_admin')
        return self.env['mail.render.mixin']._render_template(
            self.env.ref('auth_signup.reset_password_email'),
            model='res.users',
            res_ids=user.ids,
            engine='qweb_view',
            options={'post_process': True},
        )[user.id]

    def test_reset_password_email_uses_inline_logo_without_odoo_promotion(self):
        body = self._render_reset_password_email()

        self.assertIn(f'src="{INLINE_LOGO_SRC}"', body)
        self.assertNotIn('/logo.png?company=', body)
        self.assertNotIn('data:image/', body)
        self.assertNotIn('localhost', body)
        self.assertNotIn('Powered by', body)
        self.assertNotIn('odoo.com?utm_source=db&amp;utm_medium=auth', body)

    def test_reset_password_outgoing_email_embeds_logo_by_content_id(self):
        body = self._render_reset_password_email()
        mail = self.env['mail.mail'].create({
            'body_html': body,
            'email_from': 'no-reply@metric.io',
            'email_to': 'user@example.com',
            'subject': 'Reset your password',
        })

        outgoing_values = mail._prepare_outgoing_list()[0]
        inline_attachment = next(
            attachment
            for attachment in outgoing_values['attachments']
            if attachment[0] == INLINE_LOGO_FILENAME
        )
        self.assertEqual(inline_attachment[2], 'image/png')
        self.assertTrue(inline_attachment[1].startswith(b'\x89PNG\r\n\x1a\n'))

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
        image_part = next(
            part for part in message.walk() if part.get_content_type() == 'image/png'
        )

        self.assertEqual(image_part['Content-ID'], f'<{INLINE_LOGO_CID}>')
        self.assertEqual(image_part.get_content_disposition(), 'inline')
        self.assertEqual(image_part.get_filename(), 'metric_io_logo.png')
        self.assertEqual(image_part.get_payload(decode=True), inline_attachment[1])
