"""Portfolio building blocks: spend entered by hand, target quarter, client contract terms.

* Spend: each campaign keeps dated spend lines (what was paid, to whom); the
  total is compared with the campaign budget and rolls up to brands.
* Target quarter: the quarter a campaign counts for (e.g. "2026 Q4"), filled in
  from its start date and changeable; campaigns are filtered and grouped by it.
* Client terms on client brands: monthly fee and contract period, shown in the
  portfolio next to spend.
"""

from odoo import _, api, fields, models


class PlanSpend(models.Model):
    _name = 'mi.plan.spend'
    _description = 'Campaign spend'
    _order = 'date desc, id desc'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True, string='Campaign')
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    brand_id = fields.Many2one(related='plan_id.brand_id', store=True)
    currency_id = fields.Many2one(related='plan_id.currency_id')
    date = fields.Date(required=True, default=fields.Date.context_today)
    name = fields.Char(required=True, string='What', help='e.g. Facebook ads, printing, venue, influencer fee')
    partner_id = fields.Many2one('res.partner', string='Paid to')
    amount = fields.Monetary(required=True, currency_field='currency_id')


class PlanSpendTotals(models.Model):
    _inherit = 'mi.plan'

    spend_ids = fields.One2many('mi.plan.spend', 'plan_id', string='Spend')
    spent = fields.Monetary(compute='_compute_spent', store=True, currency_field='currency_id', string='Spent')
    budget_left = fields.Monetary(compute='_compute_spent', store=True, currency_field='currency_id',
                                  string='Budget left')
    target_quarter = fields.Selection('_quarters', compute='_compute_target_quarter', store=True, readonly=False,
                                      index=True, tracking=True, string='Target quarter',
                                      help='The quarter this campaign counts for. Filled in from the start date; '
                                           'change it if the campaign belongs to another quarter.')
    quarter_when = fields.Selection([('last', 'Last quarter'), ('this', 'This quarter'), ('next', 'Next quarter')],
                                    compute='_compute_quarter_when', search='_search_quarter_when',
                                    string='Quarter (relative)')

    @api.model
    def _quarters(self):
        year = fields.Date.context_today(self).year
        return [(_quarter_key(y, q), '%s Q%s' % (y, q)) for y in range(year - 3, year + 3) for q in (1, 2, 3, 4)]

    @api.depends('date_start')
    def _compute_target_quarter(self):
        for plan in self:
            if plan.date_start:
                plan.target_quarter = _quarter_key(plan.date_start.year, (plan.date_start.month - 1) // 3 + 1)

    def _relative_quarters(self):
        today = fields.Date.context_today(self)
        index = today.year * 4 + (today.month - 1) // 3
        return {when: _quarter_key((index + step) // 4, (index + step) % 4 + 1)
                for when, step in (('last', -1), ('this', 0), ('next', 1))}

    def _compute_quarter_when(self):
        keys = {v: k for k, v in self._relative_quarters().items()}
        for plan in self:
            plan.quarter_when = keys.get(plan.target_quarter, False)

    def _search_quarter_when(self, operator, value):
        values = [value] if isinstance(value, str) else list(value or [])
        if operator not in ('=', 'in'):
            raise ValueError(_('Unsupported search.'))
        quarters = self._relative_quarters()
        return [('target_quarter', 'in', [quarters[v] for v in values if v in quarters])]

    @api.depends('spend_ids.amount', 'budget')
    def _compute_spent(self):
        for plan in self:
            plan.spent = sum(plan.spend_ids.mapped('amount'))
            plan.budget_left = plan.budget - plan.spent


def _quarter_key(year, quarter):
    return '%s-Q%s' % (year, quarter)


def health_of(budget, planned, spent, goals_behind, channels_to_fix, goals_total=0):
    """('on_track' | 'at_risk' | 'off_track', [reasons]) from budget use, goals and channel problems."""
    reasons, level = [], 0
    if budget:
        if spent > budget:
            reasons.append(_('spent %(pct)s%% of the budget', pct=round(100 * spent / budget)))
            level = 2
        elif spent > 0.9 * budget:
            reasons.append(_('%(pct)s%% of the budget already spent', pct=round(100 * spent / budget)))
            level = max(level, 1)
        if planned > budget:
            reasons.append(_('campaigns plan %(pct)s%% of the budget', pct=round(100 * planned / budget)))
            level = max(level, 1)
    if goals_behind:
        reasons.append(_('%s goal(s) behind schedule', goals_behind))
        level = max(level, 2 if goals_total and goals_behind * 2 >= goals_total else 1)
    if channels_to_fix:
        reasons.append(_('%s channel(s) need fixing', channels_to_fix))
        level = max(level, 1)
    return ['on_track', 'at_risk', 'off_track'][level], reasons
