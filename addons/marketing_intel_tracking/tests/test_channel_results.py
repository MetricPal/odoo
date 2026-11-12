from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestChannelResults(TransactionCase):
    """Results by channel and source, board 10 (owner, 2026-11-12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Panel = cls.env['mi.panel']
        cls.mediums = cls.Panel._cr_mediums()
        cls.email_medium = cls.env.ref('utm.utm_medium_email')
        cls.social_medium = cls.env.ref('utm.utm_medium_social_media')
        cls.mailing = cls.env['mailing.mailing'].create({'subject': 'Spring offer', 'mailing_type': 'mail',
                                                         'body_html': '<p>Spring</p>'})
        cls.instagram = cls.env['utm.source'].create({'name': 'Instagram test'})
        Link = cls.env['link.tracker']
        cls.email_link = Link.create({'url': 'https://example.com/spring', 'medium_id': cls.email_medium.id,
                                      'source_id': cls.env.ref('utm.utm_source_mailing').id,
                                      'utm_reference': f'mailing.mailing,{cls.mailing.id}'})
        cls.social_link = Link.create({'url': 'https://example.com/post', 'medium_id': cls.social_medium.id,
                                       'source_id': cls.instagram.id})

    def _clicks(self, link, count):
        Click = self.env['link.tracker.click']
        for i in range(count):
            Click.create({'link_id': link.id, 'ip': f'10.0.0.{i + 1}'})

    def _row(self, results, key):
        return next(row for row in results['rows'] if row['key'] == key)

    def test_clicks_per_channel_and_per_mailing_or_platform(self):
        before = self.Panel._channel_results()
        self._clicks(self.email_link, 3)
        self._clicks(self.social_link, 2)
        after = self.Panel._channel_results()
        email, social = self._row(after, 'email'), self._row(after, 'social')
        self.assertEqual(email['clicks'] - self._row(before, 'email')['clicks'], 3)
        self.assertEqual(social['clicks'] - self._row(before, 'social')['clicks'], 2)
        self.assertIn('Spring offer', [s['label'] for s in email['sources']], 'Email opens into its mailings')
        self.assertIn('Instagram test', [s['label'] for s in social['sources']], 'Social opens into its platforms')
        self.assertEqual(after['totals']['clicks'] - before['totals']['clicks'], 5)

    def test_every_number_opens_its_list(self):
        self._clicks(self.email_link, 2)
        action = self.Panel.open_channel_results('clicks', 'email', ['reference', f'mailing.mailing,{self.mailing.id}'])
        self.assertEqual(action['res_model'], 'link.tracker.click')
        self.assertEqual(self.env['link.tracker.click'].search_count(action['domain']), 2)
        everything = self.Panel.open_channel_results('clicks', 'all')
        self.assertGreaterEqual(self.env['link.tracker.click'].search_count(everything['domain']), 2)

    def test_spend_counts_in_its_channel(self):
        brand = self.env['mi.brand'].create({'name': 'Spend brand', 'offering': 'Plants', 'monthly_budget': 100})
        plan = self.env['mi.plan'].create({'name': 'Spend test', 'brand_id': brand.id})
        item = self.env['mi.plan.item'].create({'plan_id': plan.id, 'channel': 'social'})
        Spend = self.env['mi.plan.spend']
        start = self.Panel._period_start()
        per_before, total_before = self.Panel._cr_spend(start, None, self.mediums)
        Spend.create({'plan_id': plan.id, 'name': 'Instagram ads', 'amount': 500, 'item_id': item.id})
        Spend.create({'plan_id': plan.id, 'name': 'Printing', 'amount': 200})
        per_after, total_after = self.Panel._cr_spend(start, None, self.mediums)
        self.assertEqual(per_after['social'] - per_before.get('social', 0), 500, 'counted in its channel')
        self.assertEqual(total_after - total_before, 700, 'a line without a channel counts in all channels only')
        action = self.Panel.open_channel_results('spend', 'social')
        self.assertIn('Instagram ads', Spend.search(action['domain']).mapped('name'))
        self.assertNotIn('Printing', Spend.search(action['domain']).mapped('name'))

    def test_block_is_on_the_department_and_my_team_views(self):
        Layout = self.env['mi.panel.layout']
        for role, after in (('hod', 'dept_tiles'), ('senior', 'team_tiles')):
            keys = [b['key'] for b in Layout._default_blocks(role)]
            self.assertIn('channel_results', keys)
            self.assertEqual(keys.index('channel_results'), keys.index(after) + 1)
        self.assertIn('channel_results', Layout._catalogue(), 'anyone can add it with Customise')

    def test_block_data_feeds_explain_this(self):
        brands = self.env['mi.brand'].search([])
        block = self.Panel._extra_blocks({'channel_results'}, brands, self.env['mi.plan'])['channel_results']
        self.assertTrue(block['explain'])
        self.assertEqual(len(block['columns']), 8)
        self.assertEqual([row[0] for row in block['table_rows']][:5],
                         ['Email', 'SMS', 'WhatsApp', 'Telegram', 'Social Media'])
        self.assertEqual(set(block['channel_results']['charts']), {'leads', 'revenue', 'clicks'})

    def test_leads_won_revenue_and_not_from_a_marketing_link(self):
        if 'crm.lead' not in self.env:
            self.skipTest('CRM is not installed')
        Lead = self.env['crm.lead']
        before = self.Panel._channel_results()
        Lead.create({'name': 'From the email', 'medium_id': self.email_medium.id,
                     'utm_reference': f'mailing.mailing,{self.mailing.id}', 'expected_revenue': 1000})
        Lead.create({'name': 'From Instagram', 'medium_id': self.social_medium.id, 'source_id': self.instagram.id})
        Lead.create({'name': 'Walked in'})
        after = self.Panel._channel_results()
        self.assertEqual(self._row(after, 'email')['leads'] - self._row(before, 'email')['leads'], 1)
        self.assertEqual(self._row(after, 'social')['leads'] - self._row(before, 'social')['leads'], 1)
        self.assertEqual(after['other']['leads'] - before['other']['leads'], 1, 'a lead with no marketing medium')
        self.assertEqual(after['totals']['leads'] - before['totals']['leads'], 3, 'shares add up to every lead')
        shares = [r['share'] for r in after['rows']] + [after['other']['share']]
        self.assertAlmostEqual(sum(shares), 100, delta=len(shares))
        leads_chart = after['charts']['leads']
        self.assertEqual(leads_chart['total'], str(after['totals']['leads']))
        self.assertTrue(all(s['path'] for s in leads_chart['slices']))
        action = self.Panel.open_channel_results('leads', 'other')
        self.assertIn('Walked in', Lead.with_context(active_test=False).search(action['domain']).mapped('name'))

    def test_one_brand_counts_only_its_campaigns(self):
        brand = self.env['mi.brand'].create({'name': 'Only brand', 'offering': 'Plants', 'monthly_budget': 100})
        self.env['mi.brand'].create({'name': 'Another brand', 'offering': 'Pots', 'monthly_budget': 100})
        self._clicks(self.email_link, 2)
        results = self.Panel._channel_results(brand.id)
        self.assertEqual(self._row(results, 'email')['clicks'], 0, 'the link has no campaign of this brand')
        self.assertIsNone(results['other'], 'no "Not from a marketing link" row for one brand')

    def test_a_marketer_without_crm_rights_sees_numbers_but_cannot_open_leads(self):
        marketer = new_test_user(self.env, 'cr_marketer', groups='marketing_intel.group_mi_user')
        results = self.Panel.with_user(marketer)._channel_results()
        if 'crm.lead' in self.env:
            self.assertFalse(results['can_open']['leads'])
