"""Executive overview (plan: Insights › Reports, approved boards 17.1 to 17.3, 2026-11-17).

Everything on the page comes from what exists: campaigns (budget, dates, owner, channels), their dated spend lines,
CRM leads, won deals and revenue tagged with the campaign, and the campaign's channels with their tracking source.
Readers: the Head of department (every team) and the Senior (their team). A period that is not over is shown without
a comparison, as the mock says.
"""

from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.tools import format_date, formatLang

from odoo.addons.marketing_intel.models.strategy import CHANNELS
from odoo.addons.marketing_intel_plan.models.plan import ACTIVE
from odoo.addons.marketing_intel_plan.models.portfolio import health_of

PERIODS = ('month', 'quarter', 'year')
ATTENTION_LIMIT = 10


def bounds(period, today):
    """(start, end) of the month, quarter or year that contains ``today``."""
    if period == 'quarter':
        start = today.replace(month=3 * ((today.month - 1) // 3) + 1, day=1)
        months = 3
    elif period == 'year':
        start, months = today.replace(month=1, day=1), 12
    else:
        start, months = today.replace(day=1), 1
    return start, start + relativedelta(months=months) - timedelta(days=1)


def _revenue(leads):
    return sum(leads.mapped('expected_revenue')) if leads else 0.0


def previous(period, start):
    """The period of the same kind right before the one that starts on ``start``."""
    months = {'month': 1, 'quarter': 3, 'year': 12}[period]
    before = start - relativedelta(months=months)
    return before, start - timedelta(days=1)


class ExecutiveOverview(models.AbstractModel):
    _name = 'mi.report.executive'
    _description = 'Executive overview'

    # ------------------------------------------------------------------ who sees what

    def _role(self):
        """'hod', 'senior', 'junior' with the marketing team installed; False without it (everyone sees it all)."""
        Department = self.env['hr.department']
        if not hasattr(Department, '_mi_department') or not Department._mi_department(self.env.company):
            return False
        from odoo.addons.marketing_intel_team.models.team import user_role
        return user_role(self.env.user)

    def _teams(self, role):
        """(options for the Team filter, the people of the chosen team or None for everyone)."""
        if role == 'senior':
            return [], self.env['mi.panel']._team_users()
        if role != 'hod':
            return [], None
        from odoo.addons.marketing_intel_team.models.team import user_role
        team = self.env['hr.department']._mi_department(self.env.company)
        options = []
        for employee in team.sudo().member_ids:
            if employee.user_id and user_role(employee.user_id) == 'senior':
                options.append({'id': employee.user_id.id, 'label': _("%s's team", employee.user_id.name)})
        return options, None

    def _team_people(self, senior_id):
        team = self.env['hr.department']._mi_department(self.env.company)
        senior = self.env['res.users'].browse(senior_id).exists()
        return senior | team.sudo().member_ids.filtered(lambda e: e.parent_id.user_id == senior).user_id

    # ------------------------------------------------------------------ the numbers of one period

    def _money(self, amount):
        return formatLang(self.env, amount or 0.0, currency_obj=self.env.company.currency_id, digits=0)

    def _plans(self, start, end, brand_id, users):
        plans = self.env['mi.plan'].search([('is_template', '=', False), ('state', '!=', 'cancelled')])
        plans = plans.filtered(lambda p: p.date_start and p.date_end and p.date_start <= end and p.date_end >= start)
        if brand_id:
            plans = plans.filtered(lambda p: p.brand_id.id == brand_id)
        if users is not None:
            plans = plans.filtered(lambda p: p.user_id in users)
        return plans

    def _figures(self, plans, start, end, channel):
        """All the numbers of ``plans`` for the dates start to end (and one channel, when chosen)."""
        begin, finish = datetime.combine(start, time.min), datetime.combine(end, time.max)
        crm = 'crm.lead' in self.env
        Lead = self.env['crm.lead'].sudo().with_context(active_test=False) if crm else None
        utm = plans.utm_campaign_id.ids
        empty = Lead.browse() if crm else self.env['res.users'].browse()
        leads = Lead.search([('campaign_id', 'in', utm), ('create_date', '>=', begin), ('create_date', '<=', finish)]) \
            if crm and utm else empty
        won = Lead.search([('campaign_id', 'in', utm), ('won_status', '=', 'won'), ('date_closed', '>=', begin),
                           ('date_closed', '<=', finish)]) if crm and utm else empty
        spend_lines = self.env['mi.plan.spend'].search([('plan_id', 'in', plans.ids), ('date', '>=', start),
                                                        ('date', '<=', end)])
        # the channels: spend by line, leads and wins by the channel's tracking source
        labels = dict(CHANNELS)
        rows = {}
        for plan in plans:
            plan_leads = leads.filtered(lambda l: l.campaign_id == plan.utm_campaign_id) if utm else leads
            plan_won = won.filtered(lambda l: l.campaign_id == plan.utm_campaign_id) if utm else won
            for item in plan.item_ids.filtered(lambda i: i.stage != 'unavailable'):
                if channel and item.channel != channel:
                    continue
                source = item.utm_source_id
                mine = plan_leads.filtered(lambda l: source and l.source_id == source)
                mine_won = plan_won.filtered(lambda l: source and l.source_id == source)
                row = rows.setdefault(item.channel, {'code': item.channel, 'label': labels.get(item.channel, item.channel),
                                                     'spend': 0.0, 'leads': 0, 'won': 0, 'revenue': 0.0})
                row['spend'] += sum(spend_lines.filtered(lambda s: s.item_id == item).mapped('amount'))
                row['leads'] += len(mine)
                row['won'] += len(mine_won)
                row['revenue'] += _revenue(mine_won)
        if channel:
            row = rows.get(channel) or {'spend': 0.0, 'leads': 0, 'won': 0, 'revenue': 0.0}
            spend, lead_count, won_count, revenue = row['spend'], row['leads'], row['won'], row['revenue']
        else:
            spend = sum(spend_lines.mapped('amount'))
            lead_count, won_count = len(leads), len(won)
            revenue = _revenue(won)
        return {'crm': crm, 'leads_rs': leads, 'won_rs': won, 'spend_lines': spend_lines, 'rows': rows,
                'spend': spend, 'leads': lead_count, 'won': won_count, 'revenue': revenue}

    @staticmethod
    def _change(now, before, lower_is_better=False, spending=False):
        """(text, tone) of the change against the previous period, or (False, False)."""
        if before is None or not before:
            return False, False
        pct = round(100 * (now - before) / before)
        arrow = '▲' if pct >= 0 else '▼'
        text = '%s %s%%' % (arrow, abs(pct))
        if pct == 0:
            return text, 'neutral'
        up = pct > 0
        if spending:
            return text, 'warn' if up else 'good'
        return text, 'good' if (up != lower_is_better) else 'bad'

    # ------------------------------------------------------------------ the page

    @api.model
    def get_filter_options(self):
        """What the search bar's Filters offer (owner, 2026-11-20: Odoo's search, as on Campaigns): the channels, and
        for the Head of department each Senior's team. A Senior's team is fixed, so it is not offered."""
        role = self._role()
        team_options = self._teams(role)[0] if role != 'junior' else []
        return {
            'channels': [{'id': code, 'label': label} for code, label in CHANNELS],
            'teams': team_options,
            'team_fixed': role == 'senior',
        }

    @api.model
    def get_overview(self, period='quarter', brand_id=False, channel=False, team=False, compare=True):
        period = period if period in PERIODS else 'quarter'
        today = fields.Date.context_today(self)
        role = self._role()
        if role == 'junior':
            return {'denied': True, 'message': _('This report is for the Head of department and the Senior.')}
        team_options, users = self._teams(role)
        if role == 'hod' and team:
            users = self._team_people(int(team))
        start, end = bounds(period, today)
        part = end >= today
        plans = self._plans(start, end, brand_id, users)
        figures = self._figures(plans, start, end, channel)
        before = None
        if compare and not part:
            p_start, p_end = previous(period, start)
            before = self._figures(self._plans(p_start, p_end, brand_id, users), p_start, p_end, channel)

        spend, leads, won, revenue = figures['spend'], figures['leads'], figures['won'], figures['revenue']
        cpl = spend / leads if leads and spend else None
        per_spend = revenue / spend if spend else None
        budget = None if channel else sum(plans.mapped('budget'))

        def _prev(key):
            return before[key] if before else None

        before_cpl = (before['spend'] / before['leads']) if before and before['leads'] else None
        before_ps = (before['revenue'] / before['spend']) if before and before['spend'] else None
        target_leads = sum(plans.mapped(lambda p: p._target('leads')))
        target_won = sum(plans.mapped(lambda p: p._target('won')))
        Lead = self.env['crm.lead'].sudo().with_context(active_test=False) if figures['crm'] else None
        utm = plans.utm_campaign_id.ids
        all_leads = Lead.search_count([('campaign_id', 'in', utm)]) if Lead is not None and utm else 0
        all_won = Lead.search_count([('campaign_id', 'in', utm), ('won_status', '=', 'won')]) \
            if Lead is not None and utm else 0
        crm = figures['crm']
        na = _('needs CRM')

        def kpi(key, label, value, change, sub):
            return {'key': key, 'label': label, 'value': value, 'change': change[0], 'tone': change[1], 'sub': sub}

        kpis = [
            kpi('spend', _('Spend'), self._money(spend), self._change(spend, _prev('spend'), spending=True),
                (_('of %(budget)s budget (%(pct)s%%)', budget=self._money(budget), pct=round(100 * spend / budget))
                 if budget else (_('no budget set') if budget is not None else ''))),
            kpi('leads', _('Leads'), '{:,}'.format(leads) if crm else '—', self._change(leads, _prev('leads')),
                (_('%s%% of campaign targets', round(100 * all_leads / target_leads)) if target_leads else '')
                if crm else na),
            kpi('cpl', _('Cost per lead'), self._money(cpl) if cpl is not None else '—',
                self._change(cpl or 0, before_cpl, lower_is_better=True) if cpl is not None else (False, False),
                _('spend ÷ leads') if crm else na),
            kpi('won', _('Won deals'), str(won) if crm else '—', self._change(won, _prev('won')),
                (_('%s%% of campaign targets', round(100 * all_won / target_won)) if target_won else '')
                if crm else na),
            kpi('revenue', _('Revenue'), self._money(revenue) if crm else '—', self._change(revenue, _prev('revenue')),
                _('won, from CRM and Sales') if crm else na),
            kpi('per_spend', _('Revenue / spend'), ('%.2f×' % per_spend) if per_spend is not None and crm else '—',
                self._change(per_spend or 0, before_ps) if per_spend is not None else (False, False),
                _('revenue ÷ spend') if crm else na),
        ]
        notes = []
        if not crm:
            notes.append(_('CRM is not installed: leads, won deals, revenue and cost per lead are not available. '
                           'Spend and budget are shown.'))
        if part:
            notes.append(_('This %s is not over, so it is shown without a comparison.', dict(
                month=_('month'), quarter=_('quarter'), year=_('year'))[period]))
        return {
            'denied': False, 'role': role or '', 'period': period, 'part': part, 'compare': bool(before),
            'label': '%s – %s' % (format_date(self.env, start), format_date(self.env, end)),
            'previous_label': dict(month=_('month'), quarter=_('quarter'), year=_('year'))[period],
            'updated': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%H:%M'),
            'filters': {
                'brands': [{'id': b.id, 'label': b.name} for b in self.env['mi.brand'].search([])],
                'channels': [{'id': code, 'label': label} for code, label in CHANNELS],
                'teams': team_options, 'team_fixed': role == 'senior',
            },
            'selected': {'brand': brand_id or 0, 'channel': channel or '', 'team': int(team or 0)},
            'empty': not plans, 'notes': notes, 'kpis': kpis,
            'trend': self._trend(figures, period, start, end, crm),
            'funnel': self._funnel(figures, plans, crm),
            'channels': self._channel_rows(figures),
            'attention': self._attention(plans),
        }

    # ------------------------------------------------------------------ the parts

    def _trend(self, figures, period, start, end, crm):
        weekly = period == 'month'
        buckets, cursor = [], start
        while cursor <= end:
            nxt = cursor + (timedelta(days=7) if weekly else relativedelta(months=1))
            buckets.append((cursor, min(nxt - timedelta(days=1), end)))
            cursor = nxt

        def index(day):
            for i, (a, b) in enumerate(buckets):
                if a <= day <= b:
                    return i
            return None

        spend, revenue, leads = [0.0] * len(buckets), [0.0] * len(buckets), [0] * len(buckets)
        for line in figures['spend_lines']:
            i = index(line.date)
            if i is not None:
                spend[i] += line.amount
        for lead in figures['won_rs']:
            i = index(lead.date_closed.date()) if lead.date_closed else None
            if i is not None:
                revenue[i] += lead.expected_revenue
        for lead in figures['leads_rs']:
            i = index(lead.create_date.date())
            if i is not None:
                leads[i] += 1
        labels = [format_date(self.env, a, date_format='d MMM') if weekly else format_date(self.env, a, date_format='MMM')
                  for a, _b in buckets]
        top = max(spend + revenue + [1.0])
        return {'labels': labels, 'spend': spend, 'revenue': revenue if crm else [], 'leads': leads,
                'top': top, 'weekly': weekly,
                'spend_label': [self._money(v) for v in spend], 'revenue_label': [self._money(v) for v in revenue]}

    def _funnel(self, figures, plans, crm):
        if not crm:
            return {'rows': [], 'leads_to_won': None, 'biggest_drop': ''}
        leads = figures['leads_rs']
        stages = self.env['crm.stage'].sudo().search([('is_won', '=', False)], order='sequence, id')
        opportunities = leads.filtered(lambda l: l.type == 'opportunity')
        rows = [{'label': _('Leads'), 'count': len(leads), 'share': None},
                {'label': _('Opportunities'), 'count': len(opportunities), 'share': None}]
        for stage in stages[1:]:
            reached = opportunities.filtered(lambda l: l.won_status == 'won' or l.stage_id.sequence >= stage.sequence)
            rows.append({'label': stage.name, 'count': len(reached), 'share': None})
        rows.append({'label': _('Won'), 'count': len(leads.filtered(lambda l: l.won_status == 'won')), 'share': None})
        top = rows[0]['count'] or 1
        worst, worst_loss = '', -1
        for i, row in enumerate(rows):
            row['width'] = round(100 * row['count'] / top, 1) if rows[0]['count'] else 0
            if i:
                before = rows[i - 1]['count']
                row['share'] = round(100 * row['count'] / before) if before else None
                row['of'] = _('of leads') if i == 1 else _('of the stage before')
                if before and before - row['count'] > worst_loss:
                    worst_loss, worst = before - row['count'], '%s → %s' % (rows[i - 1]['label'], row['label'])
        lead_count = rows[0]['count']
        return {'rows': rows, 'leads_to_won': round(100 * rows[-1]['count'] / lead_count, 1) if lead_count else None,
                'biggest_drop': worst}

    def _channel_rows(self, figures):
        rows = sorted(figures['rows'].values(), key=lambda r: -r['revenue'])
        total = sum(r['revenue'] for r in rows)
        palette = ['#71639e', '#c9a96a', '#2e8b6e', '#4f7fbf', '#c0392f', '#7a8791', '#a0522d', '#3b6e8f']
        out, best = [], None
        for index, row in enumerate(rows):
            color = palette[index % len(palette)]
            per_spend = row['revenue'] / row['spend'] if row['spend'] else None
            entry = {
                'code': row['code'], 'label': row['label'], 'color': color, 'spend': self._money(row['spend']),
                'leads': row['leads'], 'cost_per_lead': self._money(row['spend'] / row['leads'])
                if row['spend'] and row['leads'] else '—',
                'revenue': self._money(row['revenue']), 'per_spend': ('%.1f×' % per_spend) if per_spend else '—',
                'share': round(100 * row['revenue'] / total) if total else 0,
                'share_value': row['revenue'],
            }
            out.append(entry)
            if per_spend and (best is None or per_spend > best[1]):
                best = (row['label'], per_spend)
        return {'rows': out, 'total': total, 'total_label': self._money(total),
                'best': {'label': best[0], 'per_spend': '%.1f×' % best[1]} if best else None}

    def _attention(self, plans):
        rows = []
        for plan in plans.filtered(lambda p: p.state in ACTIVE):
            fix = len(plan.item_ids.filtered(lambda i: i.stage in ('blocked', 'failed')))
            level, reasons = health_of(plan.budget, plan.budget, plan.spent, 0, fix)
            if plan.budget and not plan.spent and plan.state in ('scheduled', 'live'):
                reasons.append(_('no spend entered, cost per lead is not available'))
                level = 'at_risk' if level == 'on_track' else level
            if level == 'on_track':
                continue
            rows.append({'id': plan.id, 'name': plan.name, 'brand': plan.brand_id.name, 'owner': plan.user_id.name,
                         'health': level, 'why': ', '.join(reasons)[:1].upper() + ', '.join(reasons)[1:],
                         'spent': self._money(plan.spent), 'budget': self._money(plan.budget)})
        rows.sort(key=lambda r: (r['health'] != 'off_track', r['name']))
        return rows[:ATTENTION_LIMIT]
