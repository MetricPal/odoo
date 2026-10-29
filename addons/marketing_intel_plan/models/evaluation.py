"""Results and Evaluation tabs: what the campaign achieved (CRM, Sales and UTM data) and what we make of it.

Results (for owners, HOD and CEO): revenue, revenue per spend, leads and won deals against their targets, a
takeaway, each channel's contribution (leads, wins and revenue by the channel's UTM source, cost per lead and
revenue per spend when spend lines name the channel), lead quality, the open pipeline by CRM stage as a funnel and
a comparison with an earlier campaign. Figures that are missing are shown as missing, never guessed.

Evaluation: the assessment, wins and losses (CRM lost reasons), objections and buyer language, recommendations,
and a review schedule (monthly, quarterly, every six months) that refreshes the numbers and gives the owner a To-Do.
"""

import math
from collections import Counter
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.tools import formatLang

from .plan import CHANNELS

QUALITY = [('won', 'Won', '#2e8b6e'), ('lost', 'Lost', '#d9534f'), ('open', 'Opportunity open', '#4f7fbf'),
           ('lead', 'Lead, no opportunity yet', '#8e7cc3')]


def _arcs(values, hole=0.58, r=80, c=100):
    """SVG paths for a donut (or a pie when hole is 0)."""
    total = sum(v for v in values) or 1
    paths, angle = [], -math.pi / 2
    for value in values:
        sweep = 2 * math.pi * value / total
        if value <= 0:
            paths.append('')
            continue
        if sweep >= 2 * math.pi - 1e-6:  # one segment: a full ring (two half arcs; one arc cannot close)
            if hole:
                ri = r * hole
                paths.append(f'M{c},{c - r} A{r},{r} 0 1 1 {c},{c + r} A{r},{r} 0 1 1 {c},{c - r} Z '
                             f'M{c},{c - ri:.1f} A{ri:.1f},{ri:.1f} 0 1 0 {c},{c + ri:.1f} '
                             f'A{ri:.1f},{ri:.1f} 0 1 0 {c},{c - ri:.1f} Z')
            else:
                paths.append(f'M{c},{c - r} A{r},{r} 0 1 1 {c},{c + r} A{r},{r} 0 1 1 {c},{c - r} Z')
            continue
        a2 = angle + sweep
        large = 1 if sweep > math.pi else 0
        x1, y1, x2, y2 = c + r * math.cos(angle), c + r * math.sin(angle), c + r * math.cos(a2), c + r * math.sin(a2)
        if hole:
            ri = r * hole
            x3, y3, x4, y4 = c + ri * math.cos(a2), c + ri * math.sin(a2), c + ri * math.cos(angle), c + ri * math.sin(angle)
            paths.append(f'M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} '
                         f'A{ri:.1f},{ri:.1f} 0 {large} 0 {x4:.1f},{y4:.1f} Z')
        else:
            paths.append(f'M{c},{c} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} Z')
        angle = a2
    return paths


class PlanSpendChannel(models.Model):
    _inherit = 'mi.plan.spend'

    item_id = fields.Many2one('mi.plan.item', string='Channel', domain="[('plan_id', '=', plan_id)]",
                              help='The channel this was paid for: gives each channel its cost per lead.')


class PlanItem(models.Model):
    _inherit = 'mi.plan.item'

    utm_source_id = fields.Many2one('utm.source', compute='_compute_utm_source', string='UTM source')

    def _compute_utm_source(self):
        for item in self:
            record = item._record()
            item.utm_source_id = record.source_id if record and 'source_id' in record._fields else False


class Recommendation(models.Model):
    _name = 'mi.plan.advice'
    _description = 'Campaign recommendation'
    _order = 'sequence, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, string='Recommendation')
    target = fields.Char(string='For', help='e.g. Next year-end campaign, Consideration content')
    state = fields.Selection([('new', 'New'), ('accepted', 'Accepted'), ('rejected', 'Not taken')], default='new',
                             required=True, string='Status')


class Plan(models.Model):
    _inherit = 'mi.plan'

    compare_plan_id = fields.Many2one('mi.plan', string='Compare with', domain="[('id', '!=', id), "
                                      "('is_template', '=', False), ('brand_id', '=', brand_id)]",
                                      help='An earlier campaign to compare the results with, e.g. last year\'s.')
    takeaway = fields.Text(help='The one-paragraph conclusion for management.')
    objectives_met = fields.Selection([('yes', 'Yes'), ('partly', 'Partly'), ('no', 'No')],
                                      string='Objectives met?')
    effective = fields.Text(string='Was it effective?')
    what_worked = fields.Text(string='What worked')
    to_improve = fields.Text(string='What to improve')
    next_steps = fields.Text(string='What to do next')
    objections = fields.Text(string='Objections heard', help='Common objections from leads and customers.')
    buyer_language = fields.Text(string='Words buyers use',
                                 help='How customers describe their needs, worries and decisions.')
    advice_ids = fields.One2many('mi.plan.advice', 'plan_id', string='Recommendations')
    lost_reasons = fields.Char(compute='_compute_win_loss', string='Top loss reasons')
    win_loss_label = fields.Char(compute='_compute_win_loss', string='Won · lost')
    review_monthly = fields.Boolean(string='Monthly', default=True,
                                    help='Objections and win/loss are reviewed every month while data comes in.')
    review_quarterly = fields.Boolean(string='Quarterly')
    review_halfyear = fields.Boolean(string='Every six months')
    last_review_date = fields.Date(readonly=True, copy=False)
    next_review_date = fields.Date(compute='_compute_next_review', string='Next review')

    # ------------------------------------------------------------------ CRM helpers

    def _crm_leads(self):
        self.ensure_one()
        if 'crm.lead' not in self.env or not self.utm_campaign_id:
            return self.env['crm.lead'] if 'crm.lead' in self.env else None
        return self.env['crm.lead'].sudo().with_context(active_test=False).search(
            [('campaign_id', '=', self.utm_campaign_id.id)])

    def _compute_win_loss(self):
        for plan in self:
            leads = plan._crm_leads() if plan.id else None
            if not leads:
                plan.lost_reasons, plan.win_loss_label = False, False
                continue
            won = leads.filtered(lambda l: l.won_status == 'won')
            lost = leads.filtered(lambda l: l.won_status == 'lost')
            plan.win_loss_label = '%s · %s' % (len(won), len(lost))
            reasons = Counter(lost.mapped('lost_reason_id.name'))
            plan.lost_reasons = ', '.join('%s (%s)' % (name, count) for name, count in reasons.most_common(4)) or False

    @api.depends('review_monthly', 'review_quarterly', 'review_halfyear', 'last_review_date', 'date_end')
    def _compute_next_review(self):
        for plan in self:
            plan.next_review_date = plan._next_review()

    def _next_review(self):
        self.ensure_one()
        steps = [months for flag, months in ((self.review_monthly, 1), (self.review_quarterly, 3),
                                             (self.review_halfyear, 6)) if flag]
        base = self.last_review_date or self.date_end
        if not steps or not base:
            return False
        return base + relativedelta(months=min(steps))

    # ------------------------------------------------------------------ Results data

    def _money(self, amount):
        return formatLang(self.env, amount or 0.0, currency_obj=self.currency_id, digits=0)

    def _target(self, metric):
        kpi = self.kpi_ids.filtered(lambda k: k.metric == metric)[:1]
        return kpi.target if kpi else 0

    def get_results(self):
        """Everything the Results widget shows, in one call."""
        self.ensure_one()
        self.check_access('read')
        spend = self.spent or 0.0
        revenue = self.result_revenue or 0.0
        leads_target, won_target = self._target('leads'), self._target('won')
        compare = self.compare_plan_id.sudo()
        headline = {
            'revenue': self._money(revenue),
            'revenue_delta': (round((revenue - compare.result_revenue) / compare.result_revenue * 100)
                              if compare and compare.result_revenue else None),
            'compare_name': compare.name or '',
            'per_spend': ('%.2f×' % (revenue / spend)) if spend else None,
            'spend': self._money(spend),
            'leads': self.result_leads, 'leads_target': leads_target,
            'leads_pct': round(self.result_leads / leads_target * 100) if leads_target else None,
            'won': self.result_won, 'won_target': won_target,
            'won_pct': round(self.result_won / won_target * 100) if won_target else None,
        }
        headline['leads_bar'] = min(headline['leads_pct'] or 0, 100)
        headline['won_bar'] = min(headline['won_pct'] or 0, 100)
        leads = self._crm_leads()
        crm = leads is not None
        channels = self._channel_contribution(leads) if crm else []
        best = max((c for c in channels if c['per_spend_value']), key=lambda c: c['per_spend_value'], default=None)
        quality = self._lead_quality(leads) if crm else None
        pipeline = self._pipeline(leads) if crm else None
        return {
            'headline': headline, 'crm': crm, 'channels': channels, 'best': best,
            'quality': quality, 'pipeline': pipeline, 'compare': self._comparison(),
            'missing': self._missing(crm, spend),
        }

    def _channel_contribution(self, leads):
        rows = []
        for item in self.item_ids.filtered(lambda i: i.stage != 'unavailable'):
            source = item.utm_source_id
            mine = leads.filtered(lambda l: source and l.source_id == source) if source else leads.browse()
            won = mine.filtered(lambda l: l.won_status == 'won')
            revenue = sum(won.mapped('expected_revenue'))
            if source and 'sale.order' in self.env and self.utm_campaign_id:
                orders = self.env['sale.order'].sudo().search([('campaign_id', '=', self.utm_campaign_id.id),
                                                               ('source_id', '=', source.id), ('state', '=', 'sale')])
                revenue = max(revenue, sum(orders.mapped('amount_untaxed')))
            spent = sum(self.spend_ids.filtered(lambda s: s.item_id == item).mapped('amount'))
            rows.append({
                'id': item.id, 'label': dict(CHANNELS).get(item.channel, item.channel),
                'source': source.name if source else '', 'leads': len(mine), 'won': len(won),
                'revenue': revenue, 'revenue_label': self._money(revenue),
                'cost_per_lead': self._money(spent / len(mine)) if spent and mine else None,
                'per_spend_value': revenue / spent if spent else 0,
                'per_spend': ('%.2f×' % (revenue / spent)) if spent else None,
            })
        for metric in ('revenue', 'leads', 'won'):
            top = max([r[metric] for r in rows] + [1])
            for row in rows:
                row[metric + '_pct'] = round(row[metric] / top * 100, 1)
        return sorted(rows, key=lambda r: -r['revenue'])

    def _lead_quality(self, leads):
        counts = {
            'won': len(leads.filtered(lambda l: l.won_status == 'won')),
            'lost': len(leads.filtered(lambda l: l.won_status == 'lost')),
            'open': len(leads.filtered(lambda l: l.type == 'opportunity' and l.won_status == 'pending')),
            'lead': len(leads.filtered(lambda l: l.type == 'lead' and l.won_status == 'pending')),
        }
        values = [counts[key] for key, _label, _color in QUALITY]
        paths = _arcs(values)
        return {'total': len(leads), 'segments': [
            {'key': key, 'label': label, 'color': color, 'value': counts[key], 'path': path}
            for (key, label, color), path in zip(QUALITY, paths)]}

    def _pipeline(self, leads):
        open_opps = leads.filtered(lambda l: l.type == 'opportunity' and l.won_status == 'pending' and l.active)
        stages = self.env['crm.stage'].sudo().search([('is_won', '=', False)], order='sequence, id')
        rows = []
        for stage in stages:
            reached = open_opps.filtered(lambda l: l.stage_id.sequence >= stage.sequence)
            here = open_opps.filtered(lambda l: l.stage_id == stage)
            rows.append({'label': stage.name, 'reached': len(reached),
                         'value': self._money(sum(here.mapped('expected_revenue')))})
        for index, row in enumerate(rows):
            row['width'] = max(100 - index * 16, 30)
            row['color'] = ('#a9c4b8', '#7fa99a', '#4f8a78', '#1d6b5a', '#145045')[min(index, 4)]
        return {'total': self._money(sum(open_opps.mapped('expected_revenue'))), 'count': len(open_opps),
                'rows': rows}

    def _comparison(self):
        other = self.compare_plan_id.sudo()
        if not other:
            return None

        def cpl(plan):
            return plan.spent / plan.result_leads if plan.result_leads and plan.spent else 0
        pie = _arcs([self.result_leads, other.result_leads], hole=0)
        bars = []
        for label, mine, theirs, money in ((_('Won deals'), self.result_won, other.result_won, False),
                                           (_('Revenue'), self.result_revenue, other.result_revenue, True),
                                           (_('Cost per lead'), cpl(self), cpl(other), True)):
            top = max(mine, theirs, 1)
            bars.append({'label': label, 'mine': self._money(mine) if money else str(mine),
                         'theirs': self._money(theirs) if money else str(theirs),
                         'mine_pct': round(mine / top * 90), 'theirs_pct': round(theirs / top * 90)})
        return {'name': other.name, 'mine_leads': self.result_leads, 'theirs_leads': other.result_leads,
                'pie': pie, 'bars': bars}

    def _missing(self, crm, spend):
        notes = []
        if not crm:
            notes.append(_('CRM is not installed: leads, wins and pipeline are not available.'))
        elif not self.utm_campaign_id:
            notes.append(_('No tracking campaign yet: leads and sales are counted once the drafts are prepared.'))
        if not spend:
            notes.append(_('No spend entered: revenue per spend and cost per lead are not available.'))
        elif not self.spend_ids.filtered('item_id'):
            notes.append(_('Spend lines name no channel: each channel\'s cost per lead is not available.'))
        if not self.kpi_ids:
            notes.append(_('No targets set: progress against target is not shown.'))
        return notes

    # ------------------------------------------------------------------ actions

    def action_print_report(self):
        return self.env.ref('marketing_intel_plan.action_report_campaign').report_action(self)

    @api.model
    def _cron_reviews(self):
        """Due reviews: refresh the numbers and give the owner a To-Do (objections, win/loss, results)."""
        today = fields.Date.context_today(self)
        for plan in self.search([('phase', 'in', ('results', 'evaluation')), ('is_template', '=', False),
                                 '|', '|', ('review_monthly', '=', True), ('review_quarterly', '=', True),
                                 ('review_halfyear', '=', True)]):
            due = plan._next_review()
            if not due or due > today:
                continue
            plan.action_refresh_results()
            plan.activity_schedule('mail.mail_activity_data_todo', user_id=plan.user_id.id, date_deadline=today,
                                   summary=_('Review: objections and win/loss · %s', plan.name),
                                   note=_('The results were refreshed from CRM and Sales. Update the Evaluation tab.'))
            plan.last_review_date = today
