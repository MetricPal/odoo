"""Campaign plans: a chosen option becomes linked drafts in each marketing app.

Marketing Intelligence never sends, publishes or spends. A plan creates one
UTM campaign and, per channel, a draft in the app that owns that channel
(Social, Messaging Marketing, Email, SMS, Events). Each draft is created with
the person's own permissions and still goes through its own approval in its
app. Channels without an app (content, ads, partnerships) become activities.
"""

from datetime import datetime, time, timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.marketing_intel.models.strategy import CHANNELS

# channel -> (model, label) of the app that owns it; None means a to-do activity.
TARGETS = {
    'social': ('omni.social.campaign', 'Social Marketing'),
    'messaging': ('mm.mailing', 'Messaging Marketing'),
    'email': ('mailing.mailing', 'Email Marketing'),
    'sms': ('mailing.mailing', 'SMS Marketing'),
    'event_virtual': ('event.event', 'Events'),
    'event_physical': ('event.event', 'Events'),
    'content': None, 'ads': None, 'partnership': None,
}
ACTIVE = ('draft', 'prepared', 'running')


class Plan(models.Model):
    _name = 'mi.plan'
    _description = 'Campaign plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True, tracking=True)
    recommendation_id = fields.Many2one('mi.recommendation', string='Campaign option', required=True,
                                        ondelete='restrict', index=True)
    brand_id = fields.Many2one(related='recommendation_id.brand_id', store=True, index=True)
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    currency_id = fields.Many2one(related='brand_id.currency_id')
    user_id = fields.Many2one('res.users', string='Owner', default=lambda self: self.env.user, required=True,
                              tracking=True)
    date_start = fields.Date(string='Start', required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End', required=True, tracking=True)
    budget = fields.Monetary(currency_field='currency_id')
    message = fields.Text(string='Key message', help='Starting text for every draft; each app adapts it.')
    audience = fields.Text()
    kpis = fields.Text(string='KPIs')
    utm_campaign_id = fields.Many2one('utm.campaign', string='Tracking campaign', readonly=True, copy=False)
    item_ids = fields.One2many('mi.plan.item', 'plan_id', string='Channels')
    state = fields.Selection([('draft', 'Draft'), ('prepared', 'Drafts ready'), ('running', 'Running'),
                              ('done', 'Done'), ('cancelled', 'Cancelled')],
                             default='draft', required=True, readonly=True, tracking=True, string='Status')
    clash_note = fields.Char(compute='_compute_clash_note', string='Calendar clash')
    color = fields.Integer(compute='_compute_color')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for plan in self:
            if plan.date_end < plan.date_start:
                raise ValidationError(_('The plan cannot end before it starts.'))

    @api.depends('state')
    def _compute_color(self):
        colors = {'draft': 0, 'prepared': 4, 'running': 10, 'done': 7, 'cancelled': 1}
        for plan in self:
            plan.color = colors.get(plan.state, 0)

    @api.depends('date_start', 'date_end', 'item_ids.channel', 'brand_id', 'state')
    def _compute_clash_note(self):
        """Other active plans of the brand on the same channel and dates: a fatigue warning, never a block."""
        for plan in self:
            plan.clash_note = False
            if not plan.id or plan.state not in ACTIVE or not plan.date_start or not plan.date_end:
                continue
            channels = set(plan.item_ids.mapped('channel'))
            others = self.search([('id', '!=', plan.id), ('brand_id', '=', plan.brand_id.id),
                                  ('state', 'in', ACTIVE), ('date_start', '<=', plan.date_end),
                                  ('date_end', '>=', plan.date_start)])
            clashes = others.filtered(lambda other: channels & set(other.item_ids.mapped('channel')))
            if clashes:
                plan.clash_note = _('Same audience may be contacted twice: %s overlaps on the same channels.',
                                    ', '.join(clashes.mapped('name')))

    @api.model
    def _from_recommendation(self, option):
        option.ensure_one()
        if option.state != 'chosen':
            raise UserError(_('Choose the option before planning it.'))
        start = fields.Date.context_today(self)
        lines = [option.problem, option.expected_result]
        plan = self.create({
            'name': option.name, 'recommendation_id': option.id, 'budget': option.budget,
            'date_start': start, 'date_end': start + timedelta(days=max(option.duration_days or 14, 1) - 1),
            'message': '\n\n'.join(line.strip() for line in lines if line and line.strip()),
            'audience': option.audience, 'kpis': option.kpis,
            'item_ids': [(0, 0, {'channel': channel.code}) for channel in option.channel_ids],
        })
        plan.message_post(body=_('Plan created from campaign option “%s”.', option.name))
        return plan

    # ------------------------------------------------------------------ actions

    def action_prepare(self):
        """Create the tracking campaign and every missing draft. Each draft keeps its own approval."""
        for plan in self:
            plan.check_access('write')
            if plan.state not in ('draft', 'prepared', 'running'):
                raise UserError(_('Only an active plan can prepare drafts.'))
            if not plan.utm_campaign_id:
                plan.utm_campaign_id = self.env['utm.campaign'].sudo().create(
                    {'title': plan.name, 'user_id': plan.user_id.id}).id
            for item in plan.item_ids.filtered(lambda i: not i.res_id and not i.activity_done):
                item._prepare()
            if plan.state == 'draft':
                plan.state = 'prepared'
        return True

    def action_start(self):
        self.filtered(lambda p: p.state in ('draft', 'prepared')).state = 'running'
        return True

    def action_done(self):
        self.filtered(lambda p: p.state in ACTIVE).state = 'done'
        return True

    def action_cancel(self):
        """Cancelling the plan does not touch drafts already in their apps: cancel them there."""
        self.filtered(lambda p: p.state in ACTIVE).state = 'cancelled'
        return True

    def action_reset(self):
        self.filtered(lambda p: p.state == 'cancelled').state = 'draft'
        return True

    # ------------------------------------------------------------------ texts

    def _plain(self, limit=None):
        text = (self.message or self.name or '').strip()
        return text[:limit].rstrip() if limit else text

    def _html(self):
        parts = [Markup('<h2>%s</h2>') % self.name]
        parts += [Markup('<p>%s</p>') % escape(p).replace('\n', Markup('<br/>'))
                  for p in self._plain().split('\n\n') if p.strip()]
        parts.append(Markup('<p><em>%s</em></p>') % _('Draft from a campaign plan: rewrite before sending.'))
        return Markup('').join(parts)

    def _reason(self):
        return _('Campaign plan “%(plan)s” (%(start)s to %(end)s). KPIs: %(kpis)s',
                 plan=self.name, start=self.date_start, end=self.date_end,
                 kpis=' / '.join((self.kpis or '-').splitlines()))


class PlanItem(models.Model):
    _name = 'mi.plan.item'
    _description = 'Campaign plan channel'
    _order = 'plan_id, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    channel = fields.Selection(CHANNELS, required=True)
    res_model = fields.Char(readonly=True, string='Created in')
    res_id = fields.Many2oneReference(model_field='res_model', readonly=True)
    draft_name = fields.Char(compute='_compute_draft', string='Draft')
    draft_status = fields.Char(compute='_compute_draft', string='Status in its app')
    app = fields.Char(compute='_compute_app', string='App')
    available = fields.Boolean(compute='_compute_app')
    activity_done = fields.Boolean(string='Done', help='For channels without an app: tick when it is ready.')
    note = fields.Char(readonly=True)

    @api.depends('channel')
    def _compute_app(self):
        for item in self:
            target = TARGETS.get(item.channel)
            item.app = target[1] if target else _('To-do on the plan')
            item.available = not target or target[0] in self.env

    @api.depends('res_model', 'res_id', 'activity_done')
    def _compute_draft(self):
        for item in self:
            record = item._record()
            if record:
                item.draft_name = record.display_name
                field = record._fields.get('state') or record._fields.get('stage_id')
                value = record[field.name] if field else False
                if field and field.type == 'selection':
                    value = dict(field._description_selection(self.env)).get(value, value)
                elif field:
                    value = value.display_name
                item.draft_status = value or _('Created')
            else:
                item.draft_name = False
                item.draft_status = (
                    _('Ready') if item.activity_done
                    else _('App not installed') if not item.available
                    else _('To-do scheduled') if item.note and not TARGETS.get(item.channel)
                    else _('Not prepared yet'))

    def _record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        record = self.env[self.res_model].browse(self.res_id)
        try:
            return record.exists()
        except AccessError:
            return False

    def _prepare(self):
        self.ensure_one()
        plan = self.plan_id
        target = TARGETS.get(self.channel)
        if not target:
            plan.activity_schedule('mail.mail_activity_data_todo', date_deadline=plan.date_start,
                                   user_id=plan.user_id.id,
                                   summary=_('Prepare %s', dict(CHANNELS)[self.channel]),
                                   note=plan._reason())
            self.note = _('To-do scheduled for %s.', plan.user_id.name)
            return
        model = target[0]
        if model not in self.env:
            self.note = _('Install %s to prepare this draft.', target[1])
            return
        try:
            with self.env.cr.savepoint():
                record = getattr(self, f'_draft_{self.channel}')(plan)
        except (AccessError, UserError, ValidationError) as error:
            self.note = _('Not created: %s', str(error).splitlines()[0][:200])
            return
        self.write({'res_model': record._name, 'res_id': record.id, 'note': False})
        if hasattr(record, 'message_post'):
            record.message_post(body=_('Draft created from campaign plan “%s”. It still needs its own approval.',
                                       plan.name))

    # One method per channel: drafts only, with the person's permissions.

    def _draft_social(self, plan):
        return self.env['omni.social.campaign'].create({
            'name': plan.name, 'brief': plan._plain(2000), 'reason': plan._reason(),
            'scheduled_at': datetime.combine(plan.date_start, time(2, 0)),
        })

    def _draft_messaging(self, plan):
        return self.env['mm.mailing'].create({
            'name': plan.name, 'body': plan._plain(900), 'reason': plan._reason(),
            'utm_campaign_id': plan.utm_campaign_id.id,
        })

    def _draft_email(self, plan):
        return self.env['mailing.mailing'].create({
            'subject': plan.name, 'mailing_type': 'mail', 'body_html': plan._html(), 'body_arch': plan._html(),
            'campaign_id': plan.utm_campaign_id.id, 'user_id': plan.user_id.id,
        })

    def _draft_sms(self, plan):
        return self.env['mailing.mailing'].create({
            'subject': plan.name, 'mailing_type': 'sms', 'body_plaintext': plan._plain(160),
            'campaign_id': plan.utm_campaign_id.id, 'user_id': plan.user_id.id,
        })

    def _draft_event(self, plan, virtual):
        begin = datetime.combine(plan.date_end, time(2, 0))
        values = {
            'name': plan.name, 'date_begin': begin, 'date_end': begin + timedelta(hours=2),
            'user_id': plan.user_id.id,
        }
        if 'description' in self.env['event.event']._fields:
            values['description'] = plan._html() + (Markup('<p>%s</p>') % (
                _('Online event: add the meeting link before publishing.') if virtual
                else _('Physical event: add the venue and logistics before publishing.')))
        return self.env['event.event'].create(values)

    def _draft_event_virtual(self, plan):
        return self._draft_event(plan, True)

    def _draft_event_physical(self, plan):
        return self._draft_event(plan, False)

    def action_open(self):
        self.ensure_one()
        record = self._record()
        if not record:
            raise UserError(_('This draft is not available to you.'))
        return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                'view_mode': 'form', 'target': 'current'}


class Recommendation(models.Model):
    _inherit = 'mi.recommendation'

    plan_ids = fields.One2many('mi.plan', 'recommendation_id', string='Campaign plans')
    plan_count = fields.Integer(compute='_compute_plan_count')

    def _compute_plan_count(self):
        for row in self:
            row.plan_count = len(row.plan_ids)

    def action_create_plan(self):
        self.ensure_one()
        plan = self.env['mi.plan']._from_recommendation(self)
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan', 'res_id': plan.id, 'view_mode': 'form'}

    def action_open_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan', 'name': _('Campaign plans'),
                'view_mode': 'list,form', 'domain': [('recommendation_id', '=', self.id)]}
