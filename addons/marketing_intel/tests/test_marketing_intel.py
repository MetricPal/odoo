from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.marketing_intel.models import collector

PAGE_V1 = b'<html><head><title>Pricing</title><script>x()</script></head><body><h1>Plans</h1><p>Basic RM 99</p></body></html>'
PAGE_V2 = b'<html><head><title>Pricing</title></head><body><h1>Plans</h1><p>Basic RM 79</p><p>New: AI plan</p></body></html>'
FEED = b'<?xml version="1.0"?><rss><channel><title>News</title><item><title>Launch A</title><link>https://x.example/a</link></item></channel></rss>'
FEED2 = FEED.replace(b'</channel>', b'<item><title>Launch B</title><link>https://x.example/b</link></item></channel>')


def fake_fetch(pages):
    def fetch(url, kind='page', session=None):
        body = pages[url]
        if isinstance(body, Exception):
            raise body
        if kind == 'rss':
            title, items = collector._feed_items(body)
            return collector.Result(url, 200, title, [f'{t} — {l}' for t, l in items], items)
        title, lines = collector._page_lines(body)
        return collector.Result(url, 200, title, lines)
    return fetch


@tagged('post_install', '-at_install')
class TestMarketingIntel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'mi_user', groups='marketing_intel.group_mi_user')
        cls.manager = new_test_user(cls.env, 'mi_manager', groups='marketing_intel.group_mi_manager')
        cls.brand = cls.env['mi.brand'].with_user(cls.manager).create({'name': 'metric.io', 'research_interval': 7})
        cls.rival = cls.env['mi.competitor'].with_user(cls.user).create({'brand_id': cls.brand.id, 'name': 'Rival ERP'})
        Source = cls.env['mi.source'].with_user(cls.user)
        cls.page = Source.create({'brand_id': cls.brand.id, 'competitor_id': cls.rival.id, 'name': 'Rival pricing',
                                  'url': 'https://rival.example/pricing', 'kind': 'page'})
        cls.feed = Source.create({'brand_id': cls.brand.id, 'name': 'Industry news', 'kind': 'rss',
                                  'url': 'https://news.example/feed'})

    def _approve(self, *records):
        for record in records:
            record.with_user(self.manager).write({'approval_note': 'Public page, no login, terms allow reading.'})
            record.with_user(self.manager).action_approve()

    def test_nothing_is_collected_without_approval(self):
        with patch.object(collector, 'fetch', side_effect=AssertionError('must not fetch')):
            run = self.brand.sudo()._research()
        self.assertFalse(run.finding_ids)
        with self.assertRaises(AccessError):
            self.page.with_user(self.user).action_approve()
        with self.assertRaises(UserError):  # approval needs a reason
            self.page.with_user(self.manager).action_approve()
        with self.assertRaises(AccessError):
            self.page.with_user(self.user).write({'state': 'approved'})

    def test_changes_are_detected_with_evidence_and_brief(self):
        self._approve(self.page, self.feed)
        pages = {'https://rival.example/pricing': PAGE_V1, 'https://news.example/feed': FEED}
        with patch.object(collector, 'fetch', side_effect=fake_fetch(pages)):
            first = self.brand.sudo()._research()
        self.assertEqual(set(first.finding_ids.mapped('kind')), {'baseline'})
        snapshot = self.page.snapshot_ids
        self.assertIn('Basic RM 99', snapshot.text)
        self.assertNotIn('x()', snapshot.text)
        self.assertEqual(len(snapshot.content_hash), 64)
        pages.update({'https://rival.example/pricing': PAGE_V2, 'https://news.example/feed': FEED2})
        with patch.object(collector, 'fetch', side_effect=fake_fetch(pages)):
            second = self.brand.sudo()._research()
        change = second.finding_ids.filtered(lambda f: f.kind == 'change')
        self.assertEqual(change.competitor_id, self.rival)
        self.assertIn('Basic RM 79', change.snapshot_id.diff_summary)
        self.assertIn('Basic RM 99', change.snapshot_id.diff_summary)
        item = second.finding_ids.filtered(lambda f: f.kind == 'new_item')
        self.assertEqual(item.title, 'Launch B')
        self.assertEqual((second.source_count, second.change_count, second.error_count), (2, 2, 0))
        brief = second.report_id
        self.assertTrue(brief.shared)
        data = brief._data()
        self.assertEqual(data['blocks'][0]['value'], 2)
        self.assertIn('Launch B', brief.preview_html)
        self.assertTrue(self.brand.next_research_at)

    def test_errors_and_reapproval(self):
        self._approve(self.page)
        pages = {'https://rival.example/pricing': collector.CollectError("robots.txt does not allow it")}
        with patch.object(collector, 'fetch', side_effect=fake_fetch(pages)):
            run = self.brand.sudo()._research()
        self.assertEqual(run.finding_ids.kind, 'error')
        self.assertIn('robots.txt', self.page.last_error)
        self.page.with_user(self.user).write({'url': 'https://rival.example/new-pricing'})
        self.assertEqual(self.page.state, 'proposed', 'A new address needs approval again')

    def test_collector_rules(self):
        with self.assertRaises(collector.CollectError):
            collector.fetch('http://insecure.example/')
        title, lines = collector._page_lines(PAGE_V1)
        self.assertEqual(title, 'Pricing')
        self.assertIn('Plans', lines)
        title, items = collector._feed_items(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                                             b'<rss><channel><item><title>&e;</title></item></channel></rss>')
        self.assertNotIn('root:', str(items))

    def test_options_risks_budget_check_and_brief(self):
        self.brand.with_user(self.manager).monthly_budget = 1000
        run = self.brand.sudo()._research()
        social = self.env.ref('marketing_intel.channel_social')
        Option = self.env['mi.recommendation'].with_user(self.user)
        first = Option.create({'run_id': run.id, 'brand_id': self.brand.id, 'name': 'Webinar', 'budget': 800,
                               'channel_ids': [(6, 0, social.ids)], 'confidence': 'high'})
        Option.create({'run_id': run.id, 'brand_id': self.brand.id, 'name': 'SMS promo', 'budget': 400})
        self.env['mi.risk'].with_user(self.user).create({'run_id': run.id, 'brand_id': self.brand.id,
                                                        'name': 'Consent gaps', 'likelihood': '3', 'impact': '3'})
        run.with_user(self.user).write({'summary': 'Rival cut prices.\n\nWe should answer with value.',
                                        'strengths': 'Local support'})
        old_report = run.report_id
        run.with_user(self.user).action_refresh_brief()
        budget = run.risk_ids.filtered(lambda r: r.origin == 'rule')
        self.assertEqual(budget.category, 'budget', 'options above the monthly budget are flagged')
        self.assertEqual(first.confidence, 'low', 'an option without evidence cannot claim high confidence')
        self.assertEqual(run.risk_ids.filtered(lambda r: r.name == 'Consent gaps').level, 'high')
        self.assertFalse(old_report.exists())
        titles = run.report_id.block_ids.mapped('title')
        for title in ('Analysis', 'SWOT', 'Campaign options', 'Risks'):
            self.assertIn(title, titles)
        html = run.report_id.with_user(self.user)._render_html()
        self.assertIn('Webinar', html)
        self.assertIn('Rival cut prices.', html)
        first.with_user(self.user).action_choose()
        self.assertEqual(first.state, 'chosen')
        with self.assertRaises(UserError):
            first.with_user(self.user).action_reject()
        # Refreshing again does not duplicate the automatic flag.
        run.with_user(self.user).action_refresh_brief()
        self.assertEqual(len(run.risk_ids.filtered(lambda r: r.origin == 'rule')), 1)
