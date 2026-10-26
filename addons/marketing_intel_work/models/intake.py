"""Request intake: someone asks for marketing work; the marketer accepts it and it becomes a campaign brief."""

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.marketing_intel_plan.models.plan import html2plaintext


class Request(models.Model):
    _name = 'mi.request'
    _description = 'Marketing request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state_order, wanted_by, id desc'

    name = fields.Char(string='What do you need?', required=True, tracking=True)
    brand_id = fields.Many2one('mi.brand', string='Brand', required=True, tracking=True,
                               default=lambda self: self._default_brand())
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    currency_id = fields.Many2one(related='brand_id.currency_id')
    requested_by = fields.Many2one('res.partner', string='Requested by', default=lambda self: self.env.user.partner_id,
                                   tracking=True)
    user_id = fields.Many2one('res.users', string='Handled by', tracking=True,
                              help='The marketer who decides and runs it.')
    goal = fields.Text(string='Why (the goal)')
    audience = fields.Text(string='Who it is for')
    description = fields.Html(string='Details')
    channel_ids = fields.Many2many('mi.channel', string='Channels wanted')
    wanted_by = fields.Date(string='Needed by', tracking=True)
    budget = fields.Monetary(currency_field='currency_id')
    template_id = fields.Many2one('mi.plan', string='Start from template', domain="[('is_template', '=', True)]")
    state = fields.Selection([('new', 'New'), ('accepted', 'Accepted'), ('declined', 'Declined'),
                              ('converted', 'Campaign started')], default='new', required=True, tracking=True,
                             readonly=True, group_expand=True)
    state_order = fields.Integer(compute='_compute_state_order', store=True)
    decline_reason = fields.Char(tracking=True)
    plan_id = fields.Many2one('mi.plan', string='Campaign', readonly=True, copy=False)
    next_step = fields.Char(compute='_compute_next_step')

    @api.model
    def _default_brand(self):
        brands = self.env['mi.brand'].search([], limit=2)
        return brands if len(brands) == 1 else False

    @api.model_create_multi
    def create(self, vals_list):
        requests_ = super().create(vals_list)
        for request in requests_:
            handler = request.user_id or request.brand_id.member_ids[:1]
            if handler:
                request.activity_schedule('mail.mail_activity_data_todo', user_id=handler.id,
                                          summary=_('Answer the request: %s', request.name),
                                          date_deadline=request.wanted_by or False)
        return requests_

    def _close_request_activities(self):
        self.activity_feedback(['mail.mail_activity_data_todo'], feedback=_('Done'))

    @api.depends('state')
    def _compute_state_order(self):
        order = {'new': 0, 'accepted': 1, 'converted': 2, 'declined': 3}
        for request in self:
            request.state_order = order.get(request.state, 9)

    def _compute_next_step(self):
        for request in self:
            request.next_step = {
                'new': _('Accept it (or decline with a reason), then start the campaign.'),
                'accepted': _('Start the campaign: the request becomes its brief.'),
                'declined': _('Declined: %s', request.decline_reason or '-'),
                'converted': _('The campaign is running from this request.'),
            }[request.state]

    def action_accept(self):
        for request in self.filtered(lambda r: r.state == 'new'):
            request.write({'state': 'accepted', 'user_id': request.user_id.id or self.env.uid})
            request.activity_unlink(['mail.mail_activity_data_todo'])
            request.activity_schedule('mail.mail_activity_data_todo', user_id=request.user_id.id,
                                      summary=_('Start the campaign for: %s', request.name),
                                      date_deadline=request.wanted_by or False)
            if request.requested_by:
                request.message_post(body=_('Accepted by %s.', self.env.user.name), partner_ids=request.requested_by.ids,
                                     subtype_xmlid='mail.mt_comment')
        return True

    def action_decline(self):
        for request in self.filtered(lambda r: r.state in ('new', 'accepted')):
            if not (request.decline_reason or '').strip():
                raise UserError(_('Write why it is declined (the requester sees it).'))
            request.state = 'declined'
            request._close_request_activities()
            request.message_post(body=_('Declined: %s', request.decline_reason),
                                 partner_ids=request.requested_by.ids, subtype_xmlid='mail.mt_comment')
        return True

    def action_reopen(self):
        self.filtered(lambda r: r.state == 'declined').write({'state': 'new'})
        return True

    def _brief(self):
        self.ensure_one()
        parts = [self.name]
        if self.goal:
            parts.append(_('Goal: %s', self.goal))
        details = html2plaintext(self.description)
        if details:
            parts.append(details)
        return '\n\n'.join(parts)

    def action_start_campaign(self):
        """The request becomes the brief of a new campaign (from the chosen template, if any)."""
        self.ensure_one()
        if self.state == 'converted' and self.plan_id:
            return self.plan_id._open_form()
        if self.state not in ('new', 'accepted'):
            raise UserError(_('Only an open request can start a campaign.'))
        Plan = self.env['mi.plan']
        start = fields.Date.context_today(self)
        end = self.wanted_by if self.wanted_by and self.wanted_by > start else start + timedelta(days=29)
        values = {'name': self.name, 'brand_id': self.brand_id.id, 'user_id': self.user_id.id or self.env.uid,
                  'message': self._brief(), 'audience': self.audience, 'budget': self.budget,
                  'date_start': start, 'date_end': end}
        if self.channel_ids:
            values['channel_ids'] = [(6, 0, self.channel_ids.ids)]
        if self.template_id:
            template_values = self.template_id._copy_values(is_template=False, template_id=self.template_id.id,
                                                            brand_id=self.brand_id.id, repeat='none')
            template_values.update({k: v for k, v in values.items() if v})
            values = template_values
        plan = Plan.create(values)
        self.write({'state': 'converted', 'plan_id': plan.id, 'user_id': self.user_id.id or self.env.uid})
        self._close_request_activities()
        plan.message_post(body=_('Started from the request “%s”.', self.name))
        self.message_post(body=_('Campaign started.'), partner_ids=self.requested_by.ids, subtype_xmlid='mail.mt_comment')
        return plan._open_form()


class Plan(models.Model):
    _inherit = 'mi.plan'

    request_ids = fields.One2many('mi.request', 'plan_id', string='Requests')
