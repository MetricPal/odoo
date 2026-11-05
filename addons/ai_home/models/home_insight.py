"""Insights: one record per useful fact Home shows from an app ("4 opportunities have been in one stage for more than
7 days"). Each rule is counted with the current user's own rights; a rule whose app is not installed, whose audience the
user is not in, or whose count is 0 is left out. Starter rules ship as data; administrators switch them off or add
their own (Settings > Technical > Home insights).
"""

import logging
import time
from collections import Counter
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import formatLang
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

PRIORITIES = [
    ('act_soon', 'Act soon'),
    ('incomplete', 'Incomplete information'),
    ('going_well', 'Going well'),
    ('system', 'System'),
]
TONES = [('bad', 'Red'), ('warn', 'Orange'), ('info', 'Grey'), ('good', 'Green')]
COMPLETENESS_SCAN = 1000      # records scored per rule (most recently changed first)
COMPLETENESS_ON_HOME = 3      # completeness rows on Home: the worst ones; all of them are on the dashboard
CACHE_SECONDS = 15 * 60       # completeness is scored at most every 15 minutes per user and rule
_cache = {}


class AiHomeInsight(models.Model):
    _name = 'ai.home.insight'
    _description = 'Home insight'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True, help='What the insight is about, for administrators.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    app_label = fields.Char('App', required=True, translate=True, help='Shown first in the detail line, e.g. CRM.')
    model_name = fields.Char('Model', required=True, help='Technical name, e.g. crm.lead. Ignored while not installed.')
    domain = fields.Char(default='[]', required=True,
                         help='Records the insight counts. Available: uid, today, now, days_ago(n), days_ahead(n).')
    group_xmlid = fields.Char('Audience group', help='External ID of the group that sees it. Empty: everyone who can '
                                                     'read the model.')
    required_module = fields.Char(help='Technical name of a module the rule needs besides the model, e.g. stock.')
    measure = fields.Selection([('count', 'Count'), ('completeness', 'Completeness'), ('check', 'System check')],
                               required=True, default='count',
                               help='Count: the records of the domain. Completeness: records whose weighted fields '
                                    'are less than the threshold filled. System check: a built-in health check.')
    check_key = fields.Selection([
        ('failed_emails', 'Emails that failed to send today'),
        ('failing_crons', 'Scheduled actions failing'),
        ('unhealthy_senders', 'Omnichannel senders unhealthy'),
        ('ai_engines', 'AI engines needing attention'),
        ('failed_runs', 'Workflow runs failed today'),
        ('users_without_2fa', 'Internal users without two-factor authentication'),
    ], string='Check')
    threshold = fields.Integer(default=60, help='Completeness: a record under this score (%) counts.')
    field_ids = fields.One2many('ai.home.insight.field', 'insight_id', string='Fields that count', copy=True)
    priority = fields.Selection(PRIORITIES, required=True, default='act_soon')
    tone = fields.Selection(TONES, required=True, default='warn', help='Dot colour on Home.')
    amount_field = fields.Char(help='Optional monetary or number field to total, shown as {sum}.')
    sentence = fields.Char(required=True, translate=True,
                           help='Uses {count}, e.g. "{count} contacts have no email address". The count is in bold.')
    sentence_one = fields.Char('Sentence for one', translate=True,
                               help='Used when the count is 1, e.g. "{count} contact has no email address".')
    detail = fields.Char(translate=True, help='Second line after the app; may use {count} and {sum}.')
    button_label = fields.Char(default='Open', translate=True)
    action_xmlid = fields.Char('Screen to open', help='External ID of a window action to open instead of the list, '
                                                      'e.g. stock.action_orderpoint_replenish.')

    @api.constrains('domain')
    def _check_domain(self):
        for insight in self:
            try:
                domain = safe_eval(insight.domain or '[]', insight._eval_context())
            except Exception as error:  # noqa: BLE001 - any error means the text is not a domain
                raise ValidationError(_('The domain of %(name)s is not valid: %(error)s', name=insight.name,
                                        error=error))
            if not isinstance(domain, (list, tuple)):
                raise ValidationError(_('The domain of %s must be a list.', insight.name))

    @api.constrains('sentence')
    def _check_sentence(self):
        for insight in self:
            for text in (insight.sentence, insight.sentence_one):
                if text and '{count}' not in text and '{percent}' not in text:
                    raise ValidationError(_('The sentence of %s must contain {count} or {percent}.', insight.name))

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def _eval_context(self):
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        return {
            'uid': self.env.uid,
            'today': fields.Date.to_string(today),
            'now': fields.Datetime.to_string(now),
            'days_ago': lambda n: fields.Datetime.to_string(now - timedelta(days=n)),
            'days_ahead': lambda n: fields.Date.to_string(today + timedelta(days=n)),
        }

    def _usable(self):
        self.ensure_one()
        if self.model_name not in self.env or not self.env[self.model_name].has_access('read'):
            return False
        if self.group_xmlid:
            group = self.env.ref(self.group_xmlid, raise_if_not_found=False)
            if not group or group not in self.env.user.all_group_ids:
                return False
        if self.required_module and not self.env['ir.module.module'].sudo().search_count(
                [('name', '=', self.required_module), ('state', '=', 'installed')]):
            return False
        return True

    def _domain(self):
        self.ensure_one()
        return list(safe_eval(self.domain or '[]', self._eval_context()))

    def _measure(self):
        """(count, total) with the current user's rights."""
        self.ensure_one()
        Model = self.env[self.model_name]
        domain = self._domain()
        count = Model.search_count(domain)
        total = 0.0
        if count and self.amount_field in Model._fields:
            [(total,)] = Model._read_group(domain, [], [f'{self.amount_field}:sum'])
        return count, total or 0.0

    def _money(self, total):
        Model = self.env[self.model_name]
        field = Model._fields.get(self.amount_field)
        if field is not None and field.type == 'monetary':
            return formatLang(self.env, total, currency_obj=self.env.company.currency_id, digits=0)
        return formatLang(self.env, total, digits=0)

    def _trend(self, count):
        """Compared with the user's value yesterday (from the daily snapshot), and today's snapshot written once."""
        self.ensure_one()
        Snapshot = self.env['ai.home.insight.snapshot'].sudo()
        today = fields.Date.context_today(self)
        mine = [('insight_id', '=', self.id), ('user_id', '=', self.env.uid)]
        if not Snapshot.search_count(mine + [('date', '=', today)]):
            Snapshot.create({'insight_id': self.id, 'user_id': self.env.uid, 'date': today, 'value': count})
        before = Snapshot.search(mine + [('date', '<', today)], order='date desc', limit=1)
        if not before or before.value == count:
            return ''
        diff = count - before.value
        when = _('yesterday') if before.date == today - timedelta(days=1) else _('last time')
        if diff > 0:
            return _('%(n)s more than %(when)s', n=int(diff), when=when)
        return _('%(n)s fewer than %(when)s', n=int(-diff), when=when)

    def _completeness(self):
        """{'total', 'under' (ids), 'percent', 'missing' (labels, most often first)} with the user's rights."""
        self.ensure_one()
        key = (self.env.cr.dbname, self.env.uid, tuple(self.env.companies.ids), self.id, self.write_date)
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        Model = self.env[self.model_name]
        lines = self.field_ids.filtered(lambda line: line.field_name in Model._fields and line.weight > 0)
        result = {'total': 0, 'under': [], 'percent': 0, 'missing': [], 'bands': [0, 0, 0, 0], 'missingCounts': [],
                  'scores': {}, 'empty': {}}
        weight = sum(lines.mapped('weight'))
        if lines and weight:
            order = 'write_date desc, id desc' if 'write_date' in Model._fields else 'id desc'
            records = Model.search(self._domain(), order=order, limit=COMPLETENESS_SCAN)
            missing = Counter()
            everywhere = Counter()
            for record in records:
                empty = lines.filtered(lambda line: not record[line.field_name])
                labels = [line.label or Model._fields[line.field_name].string for line in empty]
                score = 100 * (weight - sum(empty.mapped('weight'))) / weight
                result['scores'][record.id] = round(score)
                result['empty'][record.id] = empty.mapped('field_name')
                result['bands'][min(int(score // 25), 3)] += 1
                everywhere.update(labels)
                if score < self.threshold:
                    result['under'].append(record.id)
                    missing.update(labels)
            result['total'] = len(records)
            result['percent'] = round(100 * len(result['under']) / len(records)) if records else 0
            result['missing'] = [label for label, _n in missing.most_common(3)]
            result['missingCounts'] = [{'label': label, 'count': count} for label, count in everywhere.most_common(8)]
        _cache[key] = (time.monotonic(), result)
        return result

    # ------------------------------------------------------------------
    # System checks (administrators): (problems, detail, model to open, domain)
    # ------------------------------------------------------------------

    def _run_check(self):
        self.ensure_one()
        method = getattr(self, f'_check_{self.check_key}', None) if self.check_key else None
        return method() if method else (0, '', self.model_name, [])

    def _check_failed_emails(self):
        domain = [('state', '=', 'exception'), ('create_date', '>=', fields.Date.context_today(self))]
        Mail = self.env['mail.mail'].sudo()
        failed = Mail.search(domain, order='id desc', limit=1)
        reason = ' '.join((failed.failure_reason or '').split())[:90] if failed else ''
        return Mail.search_count(domain), reason, 'mail.mail', domain

    def _check_failing_crons(self):
        domain = [('failure_count', '>', 0)]
        crons = self.env['ir.cron'].sudo().search(domain, limit=3)
        return len(self.env['ir.cron'].sudo().search(domain)), ', '.join(crons.mapped('name')), 'ir.cron', domain

    def _check_unhealthy_senders(self):
        if 'omni.outbound.sender' not in self.env:
            return 0, '', 'omni.outbound.sender', []
        domain = [('health', '=', 'unhealthy')]
        Sender = self.env['omni.outbound.sender'].sudo()
        worst = Sender.search(domain, limit=1)
        return Sender.search_count(domain), worst.health_message or '', 'omni.outbound.sender', domain

    def _check_ai_engines(self):
        if 'ai.agent.engine' not in self.env:
            return 0, '', 'ai.agent.engine', []
        domain = [('state', '=', 'blocked')]
        Engine = self.env['ai.agent.engine'].sudo()
        return Engine.search_count(domain), ', '.join(Engine.search(domain, limit=3).mapped('name')), \
            'ai.agent.engine', domain

    def _check_failed_runs(self):
        if 'workflow.run' not in self.env:
            return 0, '', 'workflow.run', []
        domain = [('state', '=', 'failed'), ('is_test', '=', False),
                  ('write_date', '>=', fields.Date.context_today(self))]
        return self.env['workflow.run'].sudo().search_count(domain), '', 'workflow.run', domain

    def _check_users_without_2fa(self):
        Users = self.env['res.users'].sudo()
        if 'totp_enabled' not in Users._fields:
            return 0, '', 'res.users', []
        domain = [('share', '=', False), ('totp_enabled', '=', False)]
        return Users.search_count(domain), '', 'res.users', domain

    def _home_row(self):
        """The row Home shows, or None when there is nothing to say."""
        self.ensure_one()
        if self.measure == 'check':
            count, detail_text, _model, _domain = self._run_check()
            values = {'count': count, 'percent': '', 'total': count, 'threshold': self.threshold, 'sum': '',
                      'missing': '', 'detail': detail_text}
        elif self.measure == 'completeness':
            scored = self._completeness()
            count, total = len(scored['under']), 0.0
            values = {'count': count, 'percent': f"{scored['percent']}%", 'total': scored['total'],
                      'threshold': self.threshold, 'sum': '',
                      'missing': ', '.join(scored['missing']), 'detail': ''}
        else:
            count, total = self._measure()
            values = {'count': count, 'percent': '', 'total': count, 'threshold': self.threshold,
                      'sum': self._money(total) if self.amount_field else '', 'missing': '', 'detail': ''}
        if not count:
            return None
        sentence = self.sentence_one if count == 1 and self.sentence_one else self.sentence
        # The number in bold is the first of {count} / {percent} in the sentence.
        marks = [mark for mark in ('{count}', '{percent}') if mark in sentence]
        mark = min(marks, key=sentence.index)
        before, _sep, after = sentence.partition(mark)
        detail = self.detail.format(**values) if self.detail else ''
        trend = self._trend(count)
        return {
            'key': f'insight-{self.id}',
            'kind': 'insight',
            'insightId': self.id,
            'measure': self.measure,
            'percent': values['percent'],
            'priority': self.priority,
            'tone': self.tone,
            'before': before.format(**values),
            'number': str(values[mark[1:-1]]),
            'after': after.format(**values),
            'meta': ' · '.join(part for part in (self.app_label, detail, trend) if part),
            'buttonLabel': self.button_label or _('Open'),
        }

    @api.model
    def _home_rows(self):
        rows = []
        for insight in self.search([]):
            if not insight._usable():
                continue
            try:
                row = insight._home_row()
            except AccessError:
                continue
            except Exception:  # noqa: BLE001 - one broken rule must not break Home
                _logger.exception('Home insight %s failed', insight.id)
                continue
            if row:
                rows.append(row)
        # Completeness: only the worst few on Home (by share of records under the threshold); all on the dashboard.
        scored = sorted((row for row in rows if row['measure'] == 'completeness'),
                        key=lambda row: -int(row['percent'].rstrip('%') or 0))
        hidden = {row['key'] for row in scored[COMPLETENESS_ON_HOME:]}
        return [row for row in rows if row['key'] not in hidden]

    def action_open(self):
        """What the insight's button opens: the app screen it names, or the matching records as a list."""
        self.ensure_one()
        if not self._usable():
            raise AccessError(_('This insight is not available to you.'))
        if self.action_xmlid:
            action = self.env.ref(self.action_xmlid, raise_if_not_found=False)
            if action and action._name == 'ir.actions.act_window':
                return action._get_action_dict()
        model, domain = self.model_name, None
        if self.measure == 'check':
            _count, _detail, model, domain = self._run_check()
        elif self.measure == 'completeness':
            domain = [('id', 'in', self._completeness()['under'])]
        else:
            domain = self._domain()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': model,
            'domain': domain,
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
        }


class AiHomeInsightField(models.Model):
    _name = 'ai.home.insight.field'
    _description = 'Home insight completeness field'
    _order = 'sequence, id'

    insight_id = fields.Many2one('ai.home.insight', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    field_name = fields.Char('Field', required=True, help='Technical name; a field the model does not have is ignored.')
    label = fields.Char(translate=True, help='Shown in "Most often missing". Empty: the field\'s own label.')
    weight = fields.Integer(default=10, help='Share of the score. A field counts as filled when it has a value.')


class AiHomeInsightSnapshot(models.Model):
    _name = 'ai.home.insight.snapshot'
    _description = 'Home insight daily value'
    _order = 'date desc'

    insight_id = fields.Many2one('ai.home.insight', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    date = fields.Date(required=True, index=True)
    value = fields.Float()

    _unique_day = models.Constraint('unique(insight_id, user_id, date)', 'One value per insight, user and day.')
