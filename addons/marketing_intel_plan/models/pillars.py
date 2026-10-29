"""Campaign pillars (Awareness › Consideration › Conversion), channel schedules, and the Overview data.

Each campaign has the three pillars with their own dates, budget and objective; channels (and tasks) belong to a
pillar. The Overview shows the funnel next to the pillar timeline, the channels' statuses and the budget per month,
quarter or year: the target is each pillar's budget spread over its days, the actual is the spend entered.
"""

from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import formatLang

PILLARS = [('awareness', 'Awareness'), ('consideration', 'Consideration'), ('conversion', 'Conversion')]
PILLAR_COLORS = {'awareness': '#8e7cc3', 'consideration': '#4f7fbf', 'conversion': '#2e8b6e'}
CHANNEL_PILLAR = {'social': 'awareness', 'content': 'awareness', 'partnership': 'awareness', 'ads': 'consideration',
                  'event_virtual': 'consideration', 'event_physical': 'consideration', 'email': 'conversion',
                  'sms': 'conversion', 'messaging': 'conversion'}


class Pillar(models.Model):
    _name = 'mi.plan.pillar'
    _description = 'Campaign pillar'
    _order = 'plan_id, sequence'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    pillar = fields.Selection(PILLARS, required=True)
    sequence = fields.Integer()
    date_start = fields.Date(string='Start')
    date_end = fields.Date(string='End')
    budget = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='plan_id.currency_id')
    objective = fields.Char(help='What this pillar must achieve, e.g. "Reach 150,000 clinic owners".')

    _plan_pillar_unique = models.Constraint('UNIQUE(plan_id, pillar)', 'Each pillar once per campaign.')

    @api.depends('pillar', 'plan_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = dict(PILLARS).get(line.pillar, '')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for line in self:
            if line.date_start and line.date_end and line.date_end < line.date_start:
                raise ValidationError(_('A pillar cannot end before it starts.'))


class PlanItem(models.Model):
    _inherit = 'mi.plan.item'

    pillar = fields.Selection(PILLARS, compute='_compute_pillar', store=True, readonly=False, precompute=True)
    schedule_at = fields.Datetime(string='Schedule', copy=False,
                                  help='When this channel goes out. Email, SMS, Messaging and Social take it over; '
                                       'events keep their own dates.')

    @api.depends('channel')
    def _compute_pillar(self):
        for item in self:
            item.pillar = item.pillar or CHANNEL_PILLAR.get(item.channel, 'awareness')

    def write(self, vals):
        result = super().write(vals)
        if 'schedule_at' in vals and not self.env.context.get('mi_no_schedule_push'):
            self._push_schedule()
        return result

    def _push_schedule(self):
        """Give the channel's draft the chosen time (never in the past)."""
        floor = fields.Datetime.now() + timedelta(minutes=2)
        for item in self.filtered('schedule_at'):
            record = item._record()
            if not record:
                continue
            when = max(item.schedule_at, floor)
            if record._name == 'mailing.mailing' and record.state in ('draft', 'in_queue'):
                record.sudo().write({'schedule_type': 'scheduled', 'schedule_date': when})
            elif record._name == 'omni.social.campaign' and 'scheduled_at' in record._fields:
                record.sudo().scheduled_at = when
            elif record._name == 'mm.mailing' and 'scheduled_at' in record._fields:
                values = {'scheduled_at': when}
                if 'schedule' in record._fields:
                    values['schedule'] = 'later'
                record.sudo().write(values)

    def _prepare(self):
        result = super()._prepare()
        for item in self:
            record = item._record()
            if not record:
                continue
            if item.schedule_at:
                item._push_schedule()
            else:
                planned = item._planned_at(record)
                if planned:
                    item.with_context(mi_no_schedule_push=True).schedule_at = planned
        return result

    def _release(self):
        if self.schedule_at:
            record = self._record()
            if record and record._name == 'mailing.mailing' and record.state == 'draft':
                when = max(self.schedule_at, fields.Datetime.now() + timedelta(minutes=2))
                record.sudo().write({'schedule_type': 'scheduled', 'schedule_date': when})
                record.sudo().action_put_in_queue()
                self.note = False
                return
        return super()._release()


class Plan(models.Model):
    _inherit = 'mi.plan'

    pillar_ids = fields.One2many('mi.plan.pillar', 'plan_id', string='Pillars', copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._ensure_pillars()
        return plans

    def _ensure_pillars(self):
        for plan in self:
            have = set(plan.pillar_ids.mapped('pillar'))
            missing = [key for key, _label in PILLARS if key not in have]
            if not missing:
                continue
            start, end = plan.date_start, plan.date_end
            days = (end - start).days if start and end else 0
            spans = {'awareness': (0, 1), 'consideration': (0.25, 0.8), 'conversion': (0.55, 1)}
            share = {'awareness': 0.45, 'consideration': 0.3, 'conversion': 0.25}
            lines = []
            for index, key in enumerate(missing):
                a, b = spans[key]
                lines.append((0, 0, {
                    'pillar': key, 'sequence': [k for k, _l in PILLARS].index(key),
                    'date_start': start + timedelta(days=round(days * a)) if start else False,
                    'date_end': start + timedelta(days=round(days * b)) if start else False,
                    'budget': round((plan.budget or 0) * share[key], 2) if not have else 0}))
            plan.write({'pillar_ids': lines})

    def action_execute_now(self):
        """Send what is approved and scheduled now (the campaign must be approved)."""
        for plan in self:
            plan.check_access('write')
            if plan.state not in ('scheduled', 'live'):
                raise UserError(_('Only an approved campaign can be executed.'))
            now = fields.Datetime.now()
            items = plan.item_ids.filtered(lambda i: i.res_id and i.stage in ('scheduled', 'approved'))
            items.write({'schedule_at': now})
            plan.message_post(body=_('Executed now: %s channel(s) moved to go out in the next minutes.', len(items)))
        return True

    # ------------------------------------------------------------------ Overview

    def get_overview(self, period='month'):
        """Data for the Overview widget: pillars (funnel and timeline), today, budget per period."""
        self.ensure_one()
        self.check_access('read')
        start, end = self.date_start, self.date_end
        total = max((end - start).days, 1) if start and end else 1
        today = fields.Date.context_today(self)
        pillars = []
        for line in self.pillar_ids.sorted('sequence'):
            s, e = line.date_start or start, line.date_end or end
            pillars.append({
                'id': line.id, 'key': line.pillar, 'label': dict(PILLARS)[line.pillar], 'color': PILLAR_COLORS[line.pillar],
                'left': round(max((s - start).days, 0) / total * 100, 1) if s and start else 0,
                'width': round(max((e - s).days, 1) / total * 100, 1) if s and e else 100,
                'dates': '%s → %s' % (s.strftime('%d/%m') if s else '', e.strftime('%d/%m') if e else ''),
                'budget': formatLang(self.env, line.budget, currency_obj=self.currency_id) if line.budget else '',
                'objective': line.objective or '',
            })
        ticks = []
        if start and end:
            cursor = date(start.year, start.month, 1)
            while cursor <= end:
                if cursor >= start:
                    ticks.append({'left': round((cursor - start).days / total * 100, 1), 'label': cursor.strftime('%d %b')})
                cursor += relativedelta(months=1)
        return {
            'pillars': pillars, 'ticks': ticks,
            'today': round((today - start).days / total * 100, 1) if start and start <= today <= end else None,
            'today_label': today.strftime('%d/%m'),
            'budget': self._budget_series(period),
        }

    def _period_key(self, day, period):
        if period == 'year':
            return str(day.year)
        if period == 'quarter':
            return '%s Q%s' % (day.year, (day.month - 1) // 3 + 1)
        return day.strftime('%b %Y')

    def _budget_series(self, period):
        """Target (pillar budgets spread over their days) and actual (spend) per period."""
        self.ensure_one()
        target, actual, order = {}, {}, []

        def add(bucket, key, value):
            if key not in order:
                order.append(key)
            bucket[key] = bucket.get(key, 0.0) + value

        for line in self.pillar_ids:
            s, e = line.date_start or self.date_start, line.date_end or self.date_end
            if not line.budget or not s or not e:
                continue
            days = (e - s).days + 1
            for offset in range(days):
                day = s + timedelta(days=offset)
                add(target, self._period_key(day, period), line.budget / days)
        if not target and self.budget and self.date_start and self.date_end:
            days = (self.date_end - self.date_start).days + 1
            for offset in range(days):
                add(target, self._period_key(self.date_start + timedelta(days=offset), period), self.budget / days)
        for spend in self.spend_ids:
            add(actual, self._period_key(spend.date, period), spend.amount)
        keys = sorted(order, key=lambda k: self._period_sort(k, period))
        top = max([target.get(k, 0) for k in keys] + [actual.get(k, 0) for k in keys] + [1])
        return {'period': period, 'max': top, 'rows': [{
            'label': key, 'target': round(target.get(key, 0), 2), 'actual': round(actual.get(key, 0), 2),
            'target_label': formatLang(self.env, target.get(key, 0), currency_obj=self.currency_id),
            'actual_label': formatLang(self.env, actual.get(key, 0), currency_obj=self.currency_id),
            'target_pct': round(target.get(key, 0) / top * 100, 1), 'actual_pct': round(actual.get(key, 0) / top * 100, 1),
        } for key in keys]}

    @staticmethod
    def _period_sort(key, period):
        if period == 'year':
            return (int(key), 0)
        if period == 'quarter':
            year, quarter = key.split(' Q')
            return (int(year), int(quarter))
        return datetime.strptime(key, '%b %Y').timetuple()[:2]

    def action_open_pillar(self, pillar_id):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan.pillar', 'res_id': pillar_id,
                'views': [(False, 'form')], 'target': 'new', 'name': _('Pillar')}
