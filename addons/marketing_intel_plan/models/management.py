"""Management view of the control panel (HOD, CEO): this quarter across campaigns, from CRM, Sales and UTM data.

Spend against budget, revenue from campaigns, revenue per spend, leads, cost per lead and open pipeline; revenue
and spend per campaign; leads by UTM source; pipeline by CRM stage; the proposal approvals waiting for the viewer
(To-Do activities); and every campaign of the quarter with its stage and figures.
"""

from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.tools import formatLang

from .evaluation import _arcs

SOURCE_COLORS = ['#4f7fbf', '#8e7cc3', '#71639e', '#2e8b6e', '#b08d2d', '#c0605a', '#5b8fa8', '#c9ced6']


class PanelLayout(models.Model):
    _inherit = 'mi.panel.layout'

    @api.model
    def _catalogue(self):
        catalogue = super()._catalogue()
        catalogue['management'] = _('Management view (CRM and UTM)')
        return catalogue

    @api.model
    def _default_blocks(self, role):
        blocks = super()._default_blocks(role)
        if role == 'manager' and 'management' in self._catalogue():
            blocks.insert(0, {'key': 'management', 'width': 'full'})
        return blocks


class Panel(models.AbstractModel):
    _inherit = 'mi.panel'

    @api.model
    def get_panel(self, brand_id=False):
        data = super().get_panel(brand_id)
        if any(block['key'] == 'management' for block in data['layout']['blocks']):
            brands = self.env['mi.brand'].search([])
            selected = brands.filtered(lambda b: b.id == brand_id) or brands
            data['management'] = self._management(selected)
        return data

    def _quarter(self, today=None):
        today = today or fields.Date.context_today(self)
        start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        return start, start + relativedelta(months=3, days=-1)

    def _management(self, brands):
        start, end = self._quarter()
        Plan = self.env['mi.plan']
        plans = Plan.search([('brand_id', 'in', brands.ids), ('is_template', '=', False), ('state', '!=', 'cancelled'),
                             ('date_start', '<=', end), ('date_end', '>=', start)])
        currency = brands[:1].currency_id or self.env.company.currency_id

        def money(amount):
            return formatLang(self.env, amount or 0.0, currency_obj=currency, digits=0)

        spend = sum(self.env['mi.plan.spend'].search([('plan_id', 'in', plans.ids), ('date', '>=', start),
                                                      ('date', '<=', end)]).mapped('amount'))
        budget = sum(plans.mapped('budget'))
        revenue = sum(plans.mapped('result_revenue'))
        leads_count = sum(plans.mapped('result_leads'))
        crm = 'crm.lead' in self.env
        campaigns = plans.utm_campaign_id
        leads = self.env['crm.lead'].sudo().with_context(active_test=False).search(
            [('campaign_id', 'in', campaigns.ids)]) if crm and campaigns else None
        open_opps = leads.filtered(lambda l: l.type == 'opportunity' and l.won_status == 'pending' and l.active) \
            if leads is not None else None
        pipeline_total = sum(open_opps.mapped('expected_revenue')) if open_opps is not None else 0

        tiles = [
            {'label': _('Spend'), 'value': money(spend), 'sub': _('of %s budget', money(budget))},
            {'label': _('Revenue from campaigns'), 'value': money(revenue), 'sub': _('CRM and Sales')},
            {'label': _('Return on spend'), 'value': ('%d%%' % round(revenue / spend * 100)) if spend else '—',
             'sub': _('revenue ÷ spend')},
            {'label': _('Leads'), 'value': str(leads_count), 'sub': _('from %s campaign(s)', len(plans))},
            {'label': _('Cost per lead'), 'value': money(spend / leads_count) if spend and leads_count else '—',
             'sub': _('spend ÷ leads')},
            {'label': _('Open pipeline'), 'value': money(pipeline_total) if crm else '—', 'sub': _('from CRM')},
        ]

        top = plans.sorted(lambda p: -(p.result_revenue or p.spent or p.budget))[:8]
        scale = max([p.result_revenue for p in top] + [p.spent for p in top] + [1])
        revenue_spend = [{'id': p.id, 'name': p.name, 'spend': money(p.spent), 'revenue': money(p.result_revenue),
                          'spend_pct': round(p.spent / scale * 100, 1), 'revenue_pct': round(p.result_revenue / scale * 100, 1)}
                         for p in top]

        sources = []
        if leads:
            counts = defaultdict(int)
            for lead in leads:
                counts[lead.source_id.name or _('No source')] += 1
            ordered = sorted(counts.items(), key=lambda kv: -kv[1])
            if len(ordered) > 7:
                ordered = ordered[:6] + [(_('Other'), sum(v for _k, v in ordered[6:]))]
            paths = _arcs([v for _k, v in ordered])
            sources = [{'label': k, 'value': v, 'color': SOURCE_COLORS[i % len(SOURCE_COLORS)], 'path': paths[i]}
                       for i, (k, v) in enumerate(ordered)]

        stages = []
        if open_opps:
            by_stage = defaultdict(float)
            for opp in open_opps:
                by_stage[opp.stage_id] += opp.expected_revenue
            peak = max(by_stage.values() or [1]) or 1
            stages = [{'label': stage.name, 'value': money(amount), 'pct': round(amount / peak * 100, 1)}
                      for stage, amount in sorted(by_stage.items(), key=lambda kv: kv[0].sequence)]

        waiting = []
        for step in self.env['mi.plan.approval'].search([('state', '=', 'current'), ('user_id', '=', self.env.uid)]):
            plan = step.plan_id
            waiting.append({'id': plan.id, 'label': step._label(), 'name': plan.name,
                            'detail': '%s · %s' % (money(plan.budget), dict(plan._fields['proposal_type'].selection).get(
                                plan.proposal_type, '')),
                            'due': fields.Date.to_string(step.activity_id.date_deadline) if step.activity_id else ''})

        rows = []
        for plan in plans.sorted(lambda p: (p.date_start, p.id)):
            plan_leads = plan.result_leads
            plan_pipe = sum(open_opps.filtered(lambda l: l.campaign_id == plan.utm_campaign_id).mapped('expected_revenue')) \
                if open_opps and plan.utm_campaign_id else 0
            rows.append({'id': plan.id, 'name': plan.name, 'stage': plan.phase_label, 'phase': plan.phase,
                         'spend': money(plan.spent), 'revenue': money(plan.result_revenue),
                         'return': ('%d%%' % round(plan.result_revenue / plan.spent * 100)) if plan.spent else '—',
                         'leads': plan_leads,
                         'cpl': money(plan.spent / plan_leads) if plan.spent and plan_leads else '—',
                         'pipeline': money(plan_pipe) if crm else '—'})
        return {'period': '%s Q%s' % (start.year, (start.month - 1) // 3 + 1), 'tiles': tiles,
                'revenue_spend': revenue_spend, 'sources': sources, 'leads_total': sum(s['value'] for s in sources),
                'stages': stages, 'waiting': waiting, 'campaigns': rows, 'crm': crm}
