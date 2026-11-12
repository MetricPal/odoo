from lxml import etree

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestTracking(TransactionCase):
    """Every marketing tool tags its links with a campaign, a medium and a source; people choose only the campaign
    (owner, 2026-11-11)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.marketer = new_test_user(cls.env, 'mit_marketer', groups='marketing_intel.group_mi_user,'
                                     'mass_mailing.group_mass_mailing_user')

    def _form_field(self, model, field):
        arch = etree.fromstring(self.env[model].with_user(self.marketer).get_view(view_type='form')['arch'])
        nodes = arch.xpath(f"//field[@name='{field}']")
        self.assertTrue(nodes, f'{model}.{field} is on the form')
        return nodes[0]

    def test_email_and_sms_show_only_the_campaign(self):
        """Medium and source are kept but not shown, as in Messaging and Social."""
        for field in ('medium_id', 'source_id'):
            self.assertEqual(self._form_field('mailing.mailing', field).get('invisible'), '1')
        self.assertNotEqual(self._form_field('mailing.mailing', 'campaign_id').get('readonly'), '1',
                            'the campaign stays a choice, for Marketing users too (no Mailing Campaigns option)')

    def test_email_and_sms_get_their_medium_and_source(self):
        Mailing = self.env['mailing.mailing']
        email = Mailing.create({'subject': 'Spring', 'mailing_type': 'mail', 'body_html': '<p>Spring</p>'})
        self.assertEqual(email.medium_id, self.env.ref('utm.utm_medium_email'))
        self.assertEqual(email.source_id, self.env.ref('utm.utm_source_mailing'))
        sms = Mailing.create({'subject': 'Spring', 'mailing_type': 'sms', 'body_plaintext': 'Spring'})
        self.assertEqual(sms.medium_id, self.env.ref('mass_mailing_sms.utm_medium_sms'))
        self.assertEqual(sms.source_id, self.env.ref('mass_mailing_sms.utm_source_mass_sms'))

    def test_messaging_and_social_tag_links_with_a_medium_and_a_source(self):
        message = self.env['mm.mailing'].new({'name': 'Spring', 'channel': 'whatsapp'})
        self.assertEqual(self.env['utm.medium'].browse(message._utm_values()['medium_id']).name, 'WhatsApp')
        post = self.env['omni.social.publication'].new({'name': 'Spring'})
        values = post._utm_values()
        self.assertEqual(values['medium_id'], self.env.ref('utm.utm_medium_social_media').id)
        self.assertTrue(values['source_id'], 'the platform is the source')

    def test_social_tracking_comes_with_marketing(self):
        social_utm = self.env['ir.module.module'].search([('name', '=', 'social_utm')])
        self.assertEqual(social_utm.state, 'installed')
