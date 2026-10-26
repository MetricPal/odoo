"""What the campaign list and form show in Odoo's own layout: the summary strip above the list (like Expenses and
Sales), the form's smart buttons (budget, timeline, channels, approvals) and the market research tab."""

from odoo import _, api, fields, models
from odoo.tools import format_date, formatLang

# Stage groups of the summary strip, left to right: filter name in the search view, label, states.
STRIP = [('stage_brief', 'Brief & content', ('brief', 'content')), ('stage_review', 'Waiting approval', ('review',)),
         ('stage_scheduled', 'Scheduled', ('scheduled',)), ('stage_live', 'Running', ('live',)),
         ('stage_done', 'Done', ('done',))]


def _without_state(domain):
    """The search domain with its conditions on the stage removed, so every stage of the strip keeps its count."""
    cleaned = []
    for leaf in domain or []:
        if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] in ('state', 'status'):
            cleaned.append((1, '=', 1))
        else:
            cleaned.append(leaf)
    return cleaned


class Plan(models.Model):
    _inherit = 'mi.plan'

    duration_days = fields.Integer(compute='_compute_page', string='Days')
    timeline_label = fields.Char(compute='_compute_page', string='Timeline')
    budget_label = fields.Char(compute='_compute_page', string='Budget ')
    channel_label = fields.Char(compute='_compute_page', string='Channel names')
    approval_count = fields.Integer(compute='_compute_page', string='Approvals')
    approval_done = fields.Integer(compute='_compute_page', string='Approved')
    research_problem = fields.Text(related='recommendation_id.problem', string='Problem or opportunity')
    research_expected = fields.Text(related='recommendation_id.expected_result', string='Expected result')
    research_risks = fields.Text(related='recommendation_id.risk_notes', string='Risks')
    research_findings = fields.Many2many(related='recommendation_id.finding_ids', string='Evidence')

    @api.depends('date_start', 'date_end', 'budget', 'spent', 'channel_ids', 'review_request_id')
    def _compute_page(self):
        for plan in self:
            days = (plan.date_end - plan.date_start).days + 1 if plan.date_start and plan.date_end else 0
            plan.duration_days = days
            plan.timeline_label = '%s → %s' % (format_date(self.env, plan.date_start, date_format='d MMM'),
                                              format_date(self.env, plan.date_end, date_format='d MMM')) \
                if plan.date_start and plan.date_end else ''
            plan.budget_label = _('%s spent', formatLang(self.env, plan.spent, currency_obj=plan.currency_id)) \
                if plan.spent else _('nothing spent yet')
            plan.channel_label = ' · '.join(plan.channel_ids.mapped('name'))
            requests = plan._approval_requests()
            plan.approval_count = len(requests)
            plan.approval_done = len(requests.filtered(lambda r: r.state == 'approved'))

    def _approval_requests(self):
        self.ensure_one()
        if not self.id:
            return self.env['approval.center.request']
        return (self.sudo().review_request_id | self.sudo()._app_requests()).filtered(
            lambda r: r.state not in ('cancelled',))

    def action_open_approvals(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Approvals · %s', self.name),
                'res_model': 'approval.center.request', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._approval_requests().ids)]}

    def action_open_channels(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Channels · %s', self.name), 'res_model': 'mi.plan.item',
                'view_mode': 'list', 'domain': [('plan_id', '=', self.id)]}

    @api.model
    def get_campaign_dashboard(self, domain=None):
        """Counts per stage (ignoring stage filters, like Expenses) and three tiles, for the strip above the list."""
        base = [('is_template', '=', False)] + _without_state(domain or [])
        counts = dict(self._read_group(base, ['state'], ['__count']))
        stages = [{'filter': name, 'label': _(label), 'count': sum(counts.get(s, 0) for s in states)}
                  for name, label, states in STRIP]
        quarter = self.search(base + [('quarter_when', '=', 'this'), ('state', '!=', 'cancelled')])
        currency = quarter[:1].currency_id or self.env.company.currency_id
        return {
            'stages': stages,
            'tiles': [
                {'filter': 'needs_me', 'label': _('To do by you'), 'value': str(self.search_count(
                    base + [('needs_me', '=', True)])), 'tone': 'warning'},
                {'filter': 'this_quarter', 'label': _('Budget this quarter'),
                 'value': formatLang(self.env, sum(quarter.mapped('budget')), currency_obj=currency), 'tone': 'primary'},
                {'filter': 'my_activities', 'label': _('Your activities'), 'value': str(self.search_count(
                    base + [('activity_user_id', '=', self.env.uid)])), 'tone': 'info'},
            ],
        }
