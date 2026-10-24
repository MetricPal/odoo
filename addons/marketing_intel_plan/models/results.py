"""Measure & learn: actual results per campaign plan, targets vs actual, lessons.

Results are read from the apps that own them, through the plan's UTM campaign
and its drafts: tracked link clicks, mailing sends, leads and won deals (CRM),
confirmed sales (Sales) and event registrations. Apps are detected at run
time. Numbers are stored on the plan when refreshed (button or daily job) so
past plans stay comparable and can feed the next analysis.
"""

from datetime import timedelta

from odoo import _, api, fields, models

METRICS = [('sent', 'Messages sent'), ('clicks', 'Link clicks'), ('leads', 'Leads'), ('won', 'Won deals'),
           ('revenue', 'Revenue'), ('registrations', 'Event registrations')]


class Plan(models.Model):
    _inherit = 'mi.plan'

    result_sent = fields.Integer(string='Messages sent', readonly=True)
    result_clicks = fields.Integer(string='Link clicks', readonly=True)
    result_leads = fields.Integer(string='Leads', readonly=True)
    result_won = fields.Integer(string='Won deals', readonly=True)
    result_revenue = fields.Monetary(string='Revenue', currency_field='currency_id', readonly=True)
    result_registrations = fields.Integer(string='Event registrations', readonly=True)
    results_at = fields.Datetime(string='Results updated', readonly=True)
    cost_per_lead = fields.Monetary(compute='_compute_ratios', currency_field='currency_id', string='Cost per lead')
    return_on_budget = fields.Float(compute='_compute_ratios', string='Revenue / budget')
    kpi_ids = fields.One2many('mi.plan.kpi', 'plan_id', string='Targets')
    learning_note = fields.Text(string='What we learned',
                                help='What worked, what did not, what to try next. Used in the next analysis.')

    @api.depends('budget', 'result_leads', 'result_revenue')
    def _compute_ratios(self):
        for plan in self:
            plan.cost_per_lead = plan.budget / plan.result_leads if plan.result_leads else 0.0
            plan.return_on_budget = plan.result_revenue / plan.budget if plan.budget else 0.0

    def _measure(self):
        """Current numbers from each installed app, read with the caller's rights where it matters."""
        self.ensure_one()
        campaign = self.utm_campaign_id
        values = dict.fromkeys(['result_sent', 'result_clicks', 'result_leads', 'result_won',
                                'result_registrations'], 0)
        values['result_revenue'] = 0.0
        for item in self.item_ids:
            values['result_sent'] += item.result_sent
            values['result_registrations'] += item.result_registrations
        if campaign:
            values['result_clicks'] = self.env['link.tracker.click'].sudo().search_count(
                [('campaign_id', '=', campaign.id)]) if 'link.tracker.click' in self.env else 0
            if 'crm.lead' in self.env:
                Lead = self.env['crm.lead'].sudo().with_context(active_test=False)
                values['result_leads'] = Lead.search_count([('campaign_id', '=', campaign.id)])
                won = Lead.search([('campaign_id', '=', campaign.id), ('won_status', '=', 'won')])
                values['result_won'] = len(won)
                values['result_revenue'] = sum(won.mapped('expected_revenue'))
            if 'sale.order' in self.env:
                orders = self.env['sale.order'].sudo().search([('campaign_id', '=', campaign.id),
                                                               ('state', '=', 'sale')])
                sales = sum(o.currency_id._convert(o.amount_untaxed, self.currency_id, self.company_id,
                                                   o.date_order or fields.Date.today()) for o in orders)
                # Sales are the better revenue figure when the team confirms orders.
                values['result_revenue'] = max(values['result_revenue'], sales)
        return values

    def action_refresh_results(self):
        for plan in self:
            plan.check_access('read')
            plan.sudo().write(dict(plan._measure(), results_at=fields.Datetime.now()))
        return True

    @api.model
    def _cron_refresh_results(self):
        since = fields.Date.today() - timedelta(days=30)
        plans = self.search(['|', ('state', 'in', ('prepared', 'running')),
                             '&', ('state', '=', 'done'), ('date_end', '>=', since)])
        for plan in plans:
            plan.write(dict(plan._measure(), results_at=fields.Datetime.now()))

    def action_done(self):
        self.action_refresh_results()
        return super().action_done()

    def _learning_line(self):
        self.ensure_one()
        channels = ', '.join(dict(self.item_ids._fields['channel']._description_selection(self.env)).get(c, c)
                             for c in self.item_ids.mapped('channel'))
        targets = '; '.join(f'{k.label}: target {k.target:g}, actual {k.actual:g}' for k in self.kpi_ids) or 'no targets'
        line = (f'{self.name} ({self.date_start} to {self.date_end}, {self.state}) | channels: {channels} | '
                f'budget {self.budget:.0f} | sent {self.result_sent}, clicks {self.result_clicks}, '
                f'leads {self.result_leads}, won {self.result_won}, revenue {self.result_revenue:.0f} | {targets}')
        if self.learning_note:
            line += ' | learned: ' + ' '.join(self.learning_note.split())[:300]
        return line


class PlanItem(models.Model):
    _inherit = 'mi.plan.item'

    result_sent = fields.Integer(compute='_compute_results', string='Sent')
    result_clicks = fields.Integer(compute='_compute_results', string='Clicks')
    result_registrations = fields.Integer(compute='_compute_results', string='Registrations')

    @api.depends('res_model', 'res_id')
    def _compute_results(self):
        for item in self:
            sent = clicks = registrations = 0
            record = item._record()
            if record:
                record = record.sudo()
                if record._name == 'mailing.mailing':
                    sent, clicks = record.sent, record.clicked
                elif record._name == 'mm.mailing':
                    sent, clicks = record.sent_count, record.click_count
                elif record._name == 'event.event':
                    registrations = self.env['event.registration'].sudo().search_count(
                        [('event_id', '=', record.id), ('state', 'in', ('open', 'done'))])
            item.result_sent, item.result_clicks, item.result_registrations = sent, clicks, registrations


class PlanKpi(models.Model):
    _name = 'mi.plan.kpi'
    _description = 'Campaign plan target'
    _order = 'plan_id, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    metric = fields.Selection(METRICS, required=True, default='leads')
    label = fields.Char(compute='_compute_label')
    target = fields.Float(required=True)
    actual = fields.Float(compute='_compute_actual')
    progress = fields.Float(compute='_compute_actual', string='Progress (%)')

    @api.depends('metric')
    def _compute_label(self):
        names = dict(METRICS)
        for kpi in self:
            kpi.label = names.get(kpi.metric, '')

    @api.depends('metric', 'target', 'plan_id.result_sent', 'plan_id.result_clicks', 'plan_id.result_leads',
                 'plan_id.result_won', 'plan_id.result_revenue', 'plan_id.result_registrations')
    def _compute_actual(self):
        for kpi in self:
            kpi.actual = kpi.plan_id[f'result_{kpi.metric}'] if kpi.metric else 0.0
            kpi.progress = 100.0 * kpi.actual / kpi.target if kpi.target else 0.0


class Brand(models.Model):
    _inherit = 'mi.brand'

    def _learning_lines(self, limit=5):
        plans = self.env['mi.plan'].search([('brand_id', '=', self.id), ('state', 'in', ('running', 'done'))],
                                           order='date_end desc, id desc', limit=limit)
        return super()._learning_lines(limit) + [plan._learning_line() for plan in plans]
