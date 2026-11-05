"""System overview (administrators): figures for every app in 1.1, read from Odoo's own records.

Request counts, response times and server errors come from the request counter (ai.home.request.stat) and appear
once it has data.
"""

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.misc import format_date

# App (as shown) -> its main model. Apps whose model is not installed are left out.
APPS = [
    ('CRM', 'crm.lead'), ('Sales', 'sale.order'), ('Invoicing', 'account.move'), ('Purchase', 'purchase.order'),
    ('Inventory', 'stock.picking'), ('Employees', 'hr.employee'), ('Recruitment', 'hr.applicant'),
    ('Expenses', 'hr.expense'), ('Time Off', 'hr.leave'), ('Project', 'project.task'),
    ('Email Marketing', 'mailing.mailing'), ('Events', 'event.registration'), ('Survey', 'survey.user_input'),
    ('Contacts', 'res.partner'),
]
PERIODS = {'today': 0, '7': 7, '30': 30}


class AiHomeItem(models.Model):
    _inherit = 'ai.home.item'

    def _check_system(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('The system overview is for administrators.'))

    def _period(self, period):
        """(start, previous start) in UTC for today / last 7 / last 30 days."""
        days = PERIODS.get(str(period), 7)
        today = fields.Date.context_today(self)
        first = today - timedelta(days=max(days - 1, 0))
        start = datetime.combine(first, time.min, tzinfo=self.env.tz).astimezone(UTC).replace(tzinfo=None)
        length = timedelta(days=max(days, 1))
        return start, start - length, first

    def _apps(self):
        return [(label, model) for label, model in APPS if model in self.env]

    @api.model
    def get_system_summary(self):
        """The one line on Home's System overview card."""
        if not self.env.user.has_group('base.group_system'):
            return False
        start, _previous, _first = self._period('today')
        users = len(set(self.env['res.users.log'].sudo().search([('create_date', '>=', start)]).mapped('create_uid')))
        changed = sum(self.env[model].sudo().search_count([('write_date', '>=', start)]) for _l, model in self._apps())
        failing = sum(1 for row in self._overview_health() if row['state'] != 'ok')
        return {'users': users, 'transactions': changed, 'failing': failing}

    @api.model
    def get_system_overview(self, period='7'):
        self._check_system()
        start, previous, first = self._period(period)
        now = fields.Datetime.now()
        apps = self._apps()
        Log = self.env['res.users.log'].sudo()
        Activity = self.env['mail.activity'].sudo()
        Notification = self.env['mail.notification'].sudo()

        def changed(domain_start, domain_end=None):
            total = 0
            for _label, model in apps:
                domain = [('write_date', '>=', domain_start)] + ([('write_date', '<', domain_end)] if domain_end else [])
                total += self.env[model].sudo().search_count(domain)
            return total

        def trend(value, before):
            if not before:
                return ''
            change = round(100 * (value - before) / before)
            return f'{"▲" if change >= 0 else "▼"} {abs(change)}%'

        logins = Log.search([('create_date', '>=', start)])
        logins_before = Log.search_count([('create_date', '>=', previous), ('create_date', '<', start)])
        users = set(logins.mapped('create_uid'))
        internal = self.env['res.users'].sudo().search_count([('share', '=', False)])
        transactions, transactions_before = changed(start), changed(previous, start)
        done = Activity.with_context(active_test=False).search([('active', '=', False), ('date_done', '>=', first)])
        on_time = sum(1 for activity in done if activity.date_deadline and activity.date_done <= activity.date_deadline)
        sent = Notification.search_count([('notification_type', '=', 'email'), ('notification_status', 'in', ['pending', 'sent']),
                                          ('mail_message_id.date', '>=', start)])
        failed = Notification.search_count([('notification_type', '=', 'email'),
                                            ('notification_status', 'in', ['exception', 'bounce']),
                                            ('mail_message_id.date', '>=', start)])
        tiles = [
            {'key': 'users', 'label': _('Active users'), 'value': len(users),
             'sub': _('of %s internal users', internal), 'trend': ''},
            {'key': 'sessions', 'label': _('Sessions'), 'value': len(logins), 'sub': _('logins'),
             'trend': trend(len(logins), logins_before)},
            {'key': 'transactions', 'label': _('Transactions'), 'value': transactions,
             'sub': _('records created or changed'), 'trend': trend(transactions, transactions_before)},
            {'key': 'activities', 'label': _('Activities done'), 'value': len(done),
             'sub': _('%s%% done on time', round(100 * on_time / len(done)) if done else 0), 'trend': ''},
            {'key': 'emails', 'label': _('Emails sent'), 'value': sent,
             'sub': _('%s%% failed', round(100 * failed / (sent + failed), 1) if sent + failed else 0), 'trend': ''},
        ]
        stats = self._request_stats(start) if 'ai.home.request.stat' in self.env else None
        if stats:
            tiles.append({'key': 'requests', 'label': _('Server requests'), 'value': stats['count'],
                          'sub': _('p95 response %s ms', stats['p95']), 'trend': ''})

        # Transactions per day, all apps.
        days = (fields.Date.context_today(self) - first).days + 1
        per_day = defaultdict(int)
        for _label, model in apps:
            for day, count in self.env[model].sudo()._read_group([('write_date', '>=', start)],
                                                                  ['write_date:day'], ['__count']):
                per_day[fields.Date.to_string(day)] += count
        series = []
        for offset in range(max(days, 1)):
            day = first + timedelta(days=offset)
            series.append({'date': fields.Date.to_string(day), 'label': format_date(self.env, day, date_format='EEE d'),
                           'value': per_day.get(fields.Date.to_string(day), 0)})

        # Apps table.
        today = fields.Date.context_today(self)
        week_start = datetime.combine(today - timedelta(days=6), time.min)
        reports = set(self.env['ai.home.insight'].report_apps())
        rows = []
        for label, model in apps:
            Model = self.env[model].sudo()
            open_activities = Activity.search_count([('res_model', '=', model)])
            overdue = Activity.search_count([('res_model', '=', model), ('date_deadline', '<', today)])
            daily = {fields.Date.to_string(day): count for day, count in
                     Model._read_group([('create_date', '>=', week_start)], ['create_date:day'], ['__count'])}
            rows.append({
                'key': model, 'app': label, 'model': model,
                'hasReport': label in reports,
                'created': Model.search_count([('create_date', '>=', start)]),
                'changed': Model.search_count([('write_date', '>=', start)]),
                'openActivities': open_activities, 'overdue': overdue,
                'activeUsers': len(set(Model.search([('write_date', '>=', start)], limit=2000).mapped('write_uid'))),
                'spark': [daily.get(fields.Date.to_string(today - timedelta(days=6 - i)), 0) for i in range(7)],
            })

        # Open activities by app: overdue, due today, planned.
        activities = []
        for label, model in apps:
            base = [('res_model', '=', model)]
            late = Activity.search_count(base + [('date_deadline', '<', today)])
            due = Activity.search_count(base + [('date_deadline', '=', today)])
            planned = Activity.search_count(base + [('date_deadline', '>', today)])
            if late + due + planned:
                activities.append({'key': model, 'app': label, 'late': late, 'today': due, 'planned': planned})
        activities.sort(key=lambda row: -(row['late'] + row['today'] + row['planned']))

        Message = self.env['mail.message'].sudo()
        communication = [
            {'key': 'posted', 'label': _('Messages and notes posted'),
             'value': Message.search_count([('message_type', '=', 'comment'), ('date', '>=', start)])},
            {'key': 'received', 'label': _('Emails received'),
             'value': Message.search_count([('message_type', '=', 'email'), ('date', '>=', start)])},
            {'key': 'sent', 'label': _('Emails sent'), 'value': sent, 'sub': _('%s failed', failed) if failed else ''},
            {'key': 'sms', 'label': _('SMS sent'),
             'value': Notification.search_count([('notification_type', '=', 'sms'),
                                                 ('mail_message_id.date', '>=', start)])},
            {'key': 'inbox', 'label': _('Notifications delivered'),
             'value': Notification.search_count([('notification_type', '=', 'inbox'),
                                                 ('mail_message_id.date', '>=', start)])},
        ]
        if 'omni.conversation' in self.env:
            communication.insert(4, {'key': 'omni', 'label': _('Omnichannel conversations'),
                                     'value': self.env['omni.conversation'].sudo().search_count(
                                         [('create_date', '>=', start)])})

        self.env.cr.execute('SELECT pg_database_size(current_database())')
        [(db_size,)] = self.env.cr.fetchall()
        [(files,)] = self.env['ir.attachment'].sudo()._read_group([], [], ['file_size:sum'])
        telemetry = [
            {'key': 'db', 'label': _('Database size'), 'value': self._size(db_size)},
            {'key': 'files', 'label': _('Filestore'), 'value': self._size(files or 0)},
            {'key': 'queue', 'label': _('Mail queue'),
             'value': self.env['mail.mail'].sudo().search_count([('state', '=', 'outgoing')]), 'sub': _('waiting to send')},
            {'key': 'crons', 'label': _('Scheduled actions'),
             'value': self.env['ir.cron'].sudo().search_count([('active', '=', True)]),
             'sub': _('%s failing', self.env['ir.cron'].sudo().search_count([('failure_count', '>', 0)]))},
        ]
        if stats:
            telemetry += [
                {'key': 'errors', 'label': _('Server errors (5xx)'), 'value': stats['errors'],
                 'sub': _('%s%% of requests', stats['error_rate'])},
                {'key': 'slowest', 'label': _('Slowest page'), 'value': stats['slowest'] or '—',
                 'sub': _('p95 %s ms', stats['slowest_p95']) if stats['slowest'] else ''},
            ]
        return {
            'period': str(period), 'generatedAt': fields.Datetime.to_string(now),
            'tiles': tiles, 'series': series, 'traffic': stats['hours'] if stats else [],
            'apps': rows, 'activities': activities, 'communication': communication,
            'health': self._overview_health(), 'telemetry': telemetry,
        }

    def _overview_health(self):
        """One row per system check rule: healthy when it finds nothing."""
        Insight = self.env['ai.home.insight'].sudo()
        rows = []
        for rule in Insight.search([('measure', '=', 'check')]):
            if rule.model_name not in self.env:
                continue
            count, detail, _model, _domain = rule._run_check()
            rows.append({'key': f'check-{rule.id}', 'name': rule.app_label, 'insightId': rule.id,
                         'state': 'ok' if not count else ('warn' if rule.tone == 'warn' else 'bad'),
                         'detail': detail or (rule.name if count else _('nothing to report')), 'count': count})
        return rows

    def _request_stats(self, start):
        """Requests since start, from the request counter, plus today's requests per hour for the traffic chart."""
        Stat = self.env['ai.home.request.stat'].sudo()
        rows = Stat.search([('hour', '>=', start - timedelta(hours=1))])
        rows = rows.filtered(lambda row: row.hour >= start.replace(minute=0, second=0, microsecond=0))
        if not rows:
            return None
        buckets = [sum(rows.mapped(f'bucket_{i}')) for i in range(5)]
        count, errors = sum(rows.mapped('count')), sum(rows.mapped('errors'))
        per_route = defaultdict(lambda: [0, 0.0, [0] * 5])
        for row in rows:
            entry = per_route[row.route]
            entry[0] += row.count
            entry[1] += row.total_ms
            for i in range(5):
                entry[2][i] += row[f'bucket_{i}']
        busy = {route: entry for route, entry in per_route.items() if entry[0] >= 5} or per_route
        slowest = max(busy, key=lambda route: busy[route][1] / max(busy[route][0], 1))
        today_start, _previous, _first = self._period('today')
        hours = [0] * 24
        for row in Stat.search([('hour', '>=', today_start)]):
            index = int((row.hour - today_start).total_seconds() // 3600)
            if 0 <= index < 24:
                hours[index] += row.count
        return {
            'count': count, 'p95': Stat._p95(buckets), 'errors': errors,
            'error_rate': round(100 * errors / count, 1) if count else 0,
            'slowest': slowest, 'slowest_p95': Stat._p95(busy[slowest][2]),
            'hours': [{'hour': f'{index:02d}', 'value': value} for index, value in enumerate(hours)],
        }

    @staticmethod
    def _size(value):
        value = float(value or 0)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if value < 1024 or unit == 'TB':
                return f'{value:.1f} {unit}' if unit not in ('B', 'KB') else f'{value:.0f} {unit}'
            value /= 1024
        return ''

    @api.model
    def open_overview_app(self, model):
        """What a row of the Apps table opens (the app report comes with the insights overview)."""
        self._check_system()
        if model not in dict((m, l) for l, m in self._apps()):
            raise AccessError(_('This app is not available.'))
        return {'type': 'ir.actions.act_window', 'res_model': model, 'name': model,
                'views': [[False, 'list'], [False, 'form']], 'target': 'current'}
