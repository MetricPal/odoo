from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestHomeInsight(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'home_insight_user', name='Insight User',
                                 groups='base.group_user,base.group_partner_manager')
        cls.env['ai.home.insight'].search([]).active = False  # only the rules made here
        cls.Partner = cls.env['res.partner']
        cls.rule = cls.env['ai.home.insight'].create({
            'name': 'Test partners without phone', 'app_label': 'Contacts', 'model_name': 'res.partner',
            'domain': "[('name', 'like', 'InsightTest'), ('phone', '=', False)]",
            'priority': 'incomplete', 'tone': 'info',
            'sentence': '{count} test contacts have no phone', 'sentence_one': '{count} test contact has no phone',
            'detail': 'out of {count}', 'button_label': 'Fix',
        })

    def _rows(self, user=None):
        return {row['insightId']: row for row in
                self.env['ai.home.item'].with_user(user or self.user).get_home_data()['insights']}

    def test_zero_is_hidden_and_counts_follow_the_data(self):
        self.assertNotIn(self.rule.id, self._rows())
        self.Partner.create({'name': 'InsightTest A'})
        row = self._rows()[self.rule.id]
        self.assertEqual((row['before'], row['number'], row['after']), ('', '1', ' test contact has no phone'))
        self.assertEqual((row['tone'], row['priority'], row['buttonLabel']), ('info', 'incomplete', 'Fix'))
        self.assertTrue(row['meta'].startswith('Contacts · out of 1'))
        self.Partner.create({'name': 'InsightTest B'})
        self.assertEqual(self._rows()[self.rule.id]['after'], ' test contacts have no phone', 'plural above one')

    def test_sum_and_trend_against_yesterday(self):
        self.rule.write({'amount_field': 'color', 'detail': 'total {sum}'})
        self.Partner.create([{'name': 'InsightTest A', 'color': 2}, {'name': 'InsightTest B', 'color': 3}])
        self.env['ai.home.insight.snapshot'].create({
            'insight_id': self.rule.id, 'user_id': self.user.id, 'value': 1,
            'date': fields.Date.context_today(self.rule) - timedelta(days=1)})
        row = self._rows()[self.rule.id]
        self.assertIn('total 5', row['meta'])
        self.assertIn('1 more than yesterday', row['meta'])
        today = self.env['ai.home.insight.snapshot'].search([('insight_id', '=', self.rule.id),
                                                             ('user_id', '=', self.user.id)], order='date desc', limit=1)
        self.assertEqual(today.value, 2, "today's value is kept for tomorrow's comparison")
        self._rows()
        self.assertEqual(self.env['ai.home.insight.snapshot'].search_count([('insight_id', '=', self.rule.id)]), 2,
                         'one snapshot per user and day')

    def test_audience_and_uninstalled_apps(self):
        self.Partner.create({'name': 'InsightTest A'})
        self.rule.group_xmlid = 'base.group_system'
        self.assertNotIn(self.rule.id, self._rows())
        self.assertIn(self.rule.id, self._rows(self.env.ref('base.user_admin')))
        missing = self.rule.copy({'model_name': 'no.such.model', 'group_xmlid': False})
        self.assertNotIn(missing.id, self._rows(self.env.ref('base.user_admin')))

    def test_rules_are_validated(self):
        with self.assertRaises(ValidationError):
            self.rule.copy({'domain': 'not a domain'})
        with self.assertRaises(ValidationError):
            self.rule.copy({'sentence': 'no number here'})

    def test_open_shows_the_matching_records_or_the_named_screen(self):
        action = self.rule.with_user(self.user).action_open()
        self.assertEqual((action['res_model'], action['domain']),
                         ('res.partner', [('name', 'like', 'InsightTest'), ('phone', '=', False)]))
        self.rule.action_xmlid = 'base.action_partner_form'
        self.assertEqual(self.rule.with_user(self.user).action_open()['res_model'], 'res.partner')

    def test_starter_rules_run_on_installed_apps(self):
        starters = self.env['ai.home.insight'].with_context(active_test=False).search(
            [('id', '!=', self.rule.id)])
        self.assertTrue(starters, 'starter insights ship as data')
        starters.active = True
        admin = self.env.ref('base.user_admin')
        for rule in starters.with_user(admin):
            if not rule._usable():
                continue  # app not installed, or admin not in its audience
            if rule.measure == 'completeness':
                rule._completeness()
            else:
                rule._measure()  # each domain is valid on the installed app
        self.assertIsInstance(self.env['ai.home.insight'].with_user(admin)._home_rows(), list)

    def _completeness_rule(self, **values):
        return self.env['ai.home.insight'].create({
            'name': 'Test completeness', 'app_label': 'Contacts', 'model_name': 'res.partner',
            'domain': "[('name', 'like', 'CompleteTest')]", 'measure': 'completeness', 'threshold': 60,
            'priority': 'incomplete', 'tone': 'info', 'button_label': 'Fix',
            'sentence': '{percent} of test contacts are under {threshold}% complete',
            'detail': 'most often missing: {missing}',
            'field_ids': [fields.Command.create({'field_name': 'email', 'label': 'Email', 'weight': 50}),
                          fields.Command.create({'field_name': 'phone', 'label': 'Phone', 'weight': 30}),
                          fields.Command.create({'field_name': 'no_such_field', 'weight': 99}),
                          fields.Command.create({'field_name': 'website', 'label': 'Website', 'weight': 20})],
            **values,
        })

    def test_completeness_scores_weighted_fields(self):
        from odoo.addons.ai_home.models import home_insight
        rule = self._completeness_rule()
        full, half, empty, phone_only = self.Partner.create([
            {'name': 'CompleteTest full', 'email': 'a@x.com', 'phone': '1', 'website': 'x.com'},  # 100
            {'name': 'CompleteTest email', 'email': 'b@x.com'},                                    # 50, under
            {'name': 'CompleteTest empty'},                                                         # 0, under
            {'name': 'CompleteTest phone', 'phone': '2', 'website': 'y.com'},                      # 50, under
        ])
        home_insight._cache.clear()
        row = self._rows()[rule.id]
        self.assertEqual((row['before'], row['number'], row['after']),
                         ('', '75%', ' of test contacts are under 60% complete'))
        self.assertIn('most often missing: Email, Phone, Website', row['meta'], 'unknown fields are ignored')
        action = rule.with_user(self.user).action_open()
        self.assertEqual(set(action['domain'][0][2]), {half.id, empty.id, phone_only.id})
        self.assertNotIn(full.id, action['domain'][0][2])

    def test_home_shows_only_the_worst_completeness_rows(self):
        from odoo.addons.ai_home.models import home_insight
        self.Partner.create([{'name': 'CompleteTest a'}, {'name': 'CompleteTest b', 'email': 'b@x.com'}])
        rules = [self._completeness_rule(name=f'Rule {threshold}', threshold=threshold)
                 for threshold in (10, 60, 80, 90)]
        home_insight._cache.clear()
        shown = [rule.id for rule in rules if rule.id in self._rows()]
        self.assertEqual(len(shown), home_insight.COMPLETENESS_ON_HOME)
        self.assertNotIn(rules[0].id, shown, 'the rule with the smallest share under its threshold is left out')

    def test_starter_completeness_rules_ship(self):
        rules = self.env['ai.home.insight'].with_context(active_test=False).search([('measure', '=', 'completeness')])
        self.assertGreaterEqual(len(rules), 15, 'one per app in 1.1')
        self.assertTrue(all(rule.field_ids for rule in rules))

    def test_system_checks_are_for_administrators(self):
        admin = self.env.ref('base.user_admin')
        rule = self.env['ai.home.insight'].create({
            'name': 'Failing crons', 'app_label': 'Scheduled actions', 'model_name': 'ir.cron',
            'group_xmlid': 'base.group_system', 'measure': 'check', 'check_key': 'failing_crons',
            'priority': 'system', 'tone': 'bad', 'sentence': '{count} scheduled actions are failing',
            'sentence_one': '{count} scheduled action is failing', 'detail': '{detail}'})
        self.env['ir.cron'].search([]).failure_count = 0
        self.assertNotIn(rule.id, self._rows(admin))
        cron = self.env['ir.cron'].search([], limit=1)
        cron.failure_count = 2
        row = self._rows(admin)[rule.id]
        self.assertEqual(row['number'] + row['after'], '1 scheduled action is failing')
        self.assertIn(cron.name, row['meta'])
        self.assertNotIn(rule.id, self._rows(), 'not for ordinary users')
        action = rule.with_user(admin).action_open()
        self.assertEqual((action['res_model'], action['domain']), ('ir.cron', [('failure_count', '>', 0)]))

    def test_starter_checks_ship(self):
        checks = self.env['ai.home.insight'].with_context(active_test=False).search([('measure', '=', 'check')])
        self.assertEqual(len(checks), 6)
        self.assertEqual(set(checks.mapped('group_xmlid')), {'base.group_system'})

    def test_system_overview_is_for_administrators(self):
        from odoo.exceptions import AccessError
        admin = self.env.ref('base.user_admin')
        data = self.env['ai.home.item'].with_user(admin).get_system_overview('30')
        self.assertEqual(set(data) >= {'tiles', 'series', 'apps', 'activities', 'communication', 'health', 'telemetry'},
                         True)
        self.assertEqual(len(data['series']), 30)
        self.assertIn('Contacts', [row['app'] for row in data['apps']])
        self.assertTrue(self.env['ai.home.item'].with_user(admin).get_home_data()['systemSummary'])
        self.assertFalse(self.env['ai.home.item'].with_user(self.user).get_home_data()['systemSummary'])
        with self.assertRaises(AccessError):
            self.env['ai.home.item'].with_user(self.user).get_system_overview('7')
        with self.assertRaises(AccessError):
            self.env['ai.home.item'].with_user(admin).open_overview_app('ir.config_parameter')
        self.assertEqual(self.env['ai.home.item'].with_user(admin).open_overview_app('res.partner')['res_model'],
                         'res.partner')

    def test_insights_overview_and_app_report(self):
        from odoo.addons.ai_home.models import home_insight
        from odoo.exceptions import AccessError
        admin = self.env.ref('base.user_admin')
        rule = self._completeness_rule()
        self.Partner.create([{'name': 'CompleteTest a'}, {'name': 'CompleteTest b', 'email': 'b@x.com'},
                             {'name': 'CompleteTest c', 'email': 'c@x.com', 'phone': '1', 'website': 'c.com'}])
        home_insight._cache.clear()
        Insight = self.env['ai.home.insight'].with_user(admin)
        overview = Insight.get_insights_overview()
        row = next(r for r in overview['rows'] if r['insightId'] == rule.id)
        self.assertEqual((row['now'], row['app'], len(row['spark'])), ('67%', 'Contacts', 30))
        report = Insight.get_app_report('Contacts', rule.id)
        selected = report['selected']
        self.assertEqual((selected['insightId'], selected['total'], selected['bands']), (rule.id, 2, [1, 0, 1, 1]))
        self.assertEqual([r['score'] for r in selected['rows']], [0, 50], 'least complete first')
        self.assertTrue(selected['rows'][0]['cells'][0]['missing'])
        self.assertIn({'label': 'Phone', 'count': 2}, selected['missingCounts'])
        count_report = Insight.get_app_report('Contacts', self.rule.id)['selected']
        self.assertEqual(count_report['measure'], 'incomplete' and 'count')
        with self.assertRaises(AccessError):
            self.env['ai.home.insight'].with_user(self.user).get_insights_overview()
        self.assertTrue(next(r for r in self.env['ai.home.item'].with_user(admin).get_system_overview('7')['apps']
                             if r['app'] == 'Contacts')['hasReport'])

    def test_request_counter_feeds_the_system_overview(self):
        Stat = self.env['ai.home.request.stat']
        admin = self.env.ref('base.user_admin')
        Item = self.env['ai.home.item'].with_user(admin)
        Stat.search([]).unlink()
        self.assertEqual(Item.get_system_overview('today')['traffic'], [], 'no chart without data')
        hour = fields.Datetime.now().replace(minute=0, second=0, microsecond=0)
        Stat._add([(('db', hour, '/odoo/action-:id'), (90, 9000.0, 0, [80, 10, 0, 0, 0])),
                   (('db', hour, '/web/dataset/call_kw'), (10, 25000.0, 2, [0, 0, 5, 4, 1]))])
        Stat._add([(('db', hour, '/web/dataset/call_kw'), (10, 5000.0, 0, [5, 5, 0, 0, 0]))])
        self.assertEqual(Stat.search_count([]), 2, 'one row per hour and route, totals added up')
        stats = Item._request_stats(hour)
        self.assertEqual((stats['count'], stats['errors'], stats['error_rate'], stats['p95']), (110, 2, 1.8, 1000))
        self.assertEqual((stats['slowest'], stats['slowest_p95']), ('/web/dataset/call_kw', 3000))
        self.assertEqual(len(stats['hours']), 24)
        self.assertEqual(sum(h['value'] for h in stats['hours']), 110)
        data = Item.get_system_overview('today')
        self.assertIn('requests', [tile['key'] for tile in data['tiles']])
        self.assertIn('errors', [row['key'] for row in data['telemetry']])
        self.assertEqual(len(data['traffic']), 24)
