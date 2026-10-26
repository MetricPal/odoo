"""Campaigns: brief, content, one review, then every channel goes out in its own app.

A campaign creates one UTM campaign and, per channel, a draft in the app that
owns it (Social, Messaging Marketing, Email, SMS, Events). Drafts are written
by a person or by the AI assistant. One review covers the whole campaign:

* Messaging and Social keep their own approvals (assigned approvers, frozen
  content). Sending the campaign for review submits them; the campaign review
  screen lets an approver decide them all at once, each decision checked and
  audited by its own app.
* Email, SMS and Events have no approval of their own: the campaign approval
  request (Approval Center, type "Marketing campaign") is their gate. Only once
  it is approved does the campaign schedule them (``action_release``).

Status follows the channels: Brief → Content → Review → Scheduled → Live →
Done. Channels without an app (content, ads, partnerships) become to-dos.
"""

import html as htmllib
import re
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from zoneinfo import ZoneInfo
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_date

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
STAGES = [('brief', 'Brief'), ('content', 'Content'), ('review', 'Review'), ('scheduled', 'Scheduled'),
          ('live', 'Live'), ('done', 'Done'), ('cancelled', 'Cancelled')]
ACTIVE = ('brief', 'content', 'review', 'scheduled', 'live')
ITEM_STAGES = [('not_started', 'Not started'), ('writing', 'AI is writing'), ('draft', 'Being written'),
               ('blocked', 'Needs fixing'), ('needs_review', 'Waiting for approval'), ('approved', 'Approved'),
               ('scheduled', 'Scheduled'), ('out', 'Sent'), ('failed', 'Failed'), ('todo', 'To-do'),
               ('todo_done', 'Done'), ('unavailable', 'App not installed')]
BEFORE_REVIEW = ('brief', 'content', 'review')
SEND_HOUR = 9  # local time the campaign's email and SMS go out on the start day


def text_to_html(text):
    """Plain text with blank-line paragraphs as simple HTML."""
    return Markup('').join(Markup('<p>%s</p>') % escape(p).replace('\n', Markup('<br/>'))
                           for p in (text or '').split('\n\n') if p.strip())


def html2plaintext(html):
    """Readable text for the review: paragraphs kept, no markup symbols."""
    text = re.sub(r'(?i)</(p|div|h[1-6]|tr)>', '\n\n', str(html or ''))
    text = re.sub(r'(?i)<br\s*/?>|</li>', '\n', text)
    text = htmllib.unescape(re.sub(r'<[^>]+>', '', text)).replace('\xa0', ' ')
    return re.sub(r'\n\s*\n+', '\n\n', '\n'.join(line.strip() for line in text.splitlines())).strip()


class _Problems(Exception):
    """Internal: undo a partial submission; the problems are written on the channel lines."""


class Plan(models.Model):
    _name = 'mi.plan'
    _description = 'Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True, tracking=True, string='Campaign')
    recommendation_id = fields.Many2one('mi.recommendation', string='From suggestion', ondelete='restrict', index=True,
                                        help='The suggested campaign this one was started from, if any.')
    brand_id = fields.Many2one('mi.brand', required=True, index=True, tracking=True, compute='_compute_brand_id',
                               store=True, readonly=False, precompute=True)
    goal_id = fields.Many2one('mi.goal', string='Goal', domain="[('brand_id', '=', brand_id)]", tracking=True,
                              help='The goal this campaign works towards; its results count towards the goal.')
    channel_ids = fields.Many2many('mi.channel', string='Channels',
                                   help='Where the campaign runs; one draft is prepared per channel.')
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    currency_id = fields.Many2one(related='brand_id.currency_id')
    user_id = fields.Many2one('res.users', string='Owner', default=lambda self: self.env.user, required=True,
                              tracking=True)
    worker = fields.Selection([('me', 'Me'), ('ai', 'AI assistant')], string='Who does the work', default='me',
                              required=True, tracking=True,
                              help='Me: you write each channel. AI assistant: it fills the brief, writes every channel '
                                   'and sends the campaign for review; you only approve.')
    date_start = fields.Date(string='Start', required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End', required=True, tracking=True,
                           default=lambda self: fields.Date.context_today(self) + timedelta(days=29))
    budget = fields.Monetary(currency_field='currency_id')
    message = fields.Text(string='Key message', help='Starting text for every draft; each app adapts it.')
    audience = fields.Text()
    kpis = fields.Text(string='KPIs')
    utm_campaign_id = fields.Many2one('utm.campaign', string='Tracking campaign', readonly=True, copy=False)
    item_ids = fields.One2many('mi.plan.item', 'plan_id', string='Channel lines')
    state = fields.Selection(STAGES, default='brief', required=True, readonly=True, tracking=True,
                             string='Stage', copy=False, group_expand=True)
    status = fields.Selection(STAGES, compute='_compute_status', string='Status',
                              help='Brief: nothing prepared yet. Content: drafts are being written. Review: waiting '
                                   'for approval. Scheduled: approved, going out at the planned time. Live: at least '
                                   'one channel is out. Done: finished (automatically after the end date).')
    review_request_id = fields.Many2one('approval.center.request', string='Campaign approval', readonly=True,
                                        copy=False)
    channels_out = fields.Integer(compute='_compute_progress', string='Channels sent',
                                  help='Channels already sent or published (or to-dos done), out of all channels.')
    channel_count = fields.Integer(compute='_compute_progress', string='Channels')
    day_label = fields.Char(compute='_compute_progress', string='Timing')
    waiting_for = fields.Char(compute='_compute_progress', string='Waiting for')
    next_step = fields.Char(compute='_compute_needs_me', string='Next step',
                            help='What has to happen next, and who does it.')
    needs_me = fields.Boolean(compute='_compute_needs_me', search='_search_needs_me', string='Your action needed',
                              help='You have something to do on this campaign.')
    my_todo = fields.Char(compute='_compute_needs_me', string='What you need to do')
    can_review = fields.Boolean(compute='_compute_needs_me')
    clash_note = fields.Char(compute='_compute_clash_note', string='Calendar clash')
    color = fields.Integer(compute='_compute_color')
    is_template = fields.Boolean(string='Template', copy=False, index=True,
                                 help='A reusable campaign: it never runs; "Use this template" starts a campaign from it.')
    template_id = fields.Many2one('mi.plan', string='From template', readonly=True, copy=False,
                                  domain=[('is_template', '=', True)])
    template_source_id = fields.Many2one('mi.plan', string='Saved from', readonly=True, copy=False, index=True,
                                         help='The campaign this template was saved from.')
    saved_template_id = fields.Many2one('mi.plan', compute='_compute_saved_template', string='Its template')
    repeat = fields.Selection([('none', 'Does not repeat'), ('weekly', 'Every week'), ('monthly', 'Every month')],
                              default='none', required=True, string='Repeat', tracking=True,
                              help='Each period a new copy of this campaign is created a few days before it starts '
                                   'and sent for the one-click review (the AI assistant refreshes the text when it '
                                   'does the work).')
    repeat_until = fields.Date(string='Repeat until')
    series_id = fields.Many2one('mi.plan', string='Series', readonly=True, copy=False, index=True,
                                help='The first campaign of a repeating series.')
    next_run_date = fields.Date(compute='_compute_next_run', string='Next run starts')

    template_use_count = fields.Integer(compute='_compute_template_use_count', string='Used', help='Campaigns started from this template, and their copies.')

    def _compute_saved_template(self):
        for plan in self:
            plan.saved_template_id = plan._own_template() if plan.id and not plan.is_template else False

    def _compute_template_use_count(self):
        counts = dict(self._read_group([('template_id', 'in', self.ids)], ['template_id'], ['__count']))
        for plan in self:
            plan.template_use_count = counts.get(plan, 0)

    def _own_template(self):
        """The template of this campaign's family: the one saved from it, or the one it was started (or copied) from."""
        self.ensure_one()
        template = self.search([('is_template', '=', True), ('template_source_id', '=', self.id)], limit=1)
        if not template and self.template_id.is_template:
            template = self.template_id
        return template

    @api.depends('repeat', 'repeat_until', 'date_start', 'state')
    def _compute_next_run(self):
        for plan in self:
            plan.next_run_date = plan._next_start() if plan._repeats_next() else False

    def _next_start(self):
        self.ensure_one()
        if self.repeat == 'weekly':
            return self.date_start + timedelta(days=7)
        if self.repeat == 'monthly':
            return self.date_start + relativedelta(months=1)
        return False

    def _repeats_next(self):
        """True when this is the latest campaign of a live series and it has a next run."""
        self.ensure_one()
        if self.is_template or self.repeat == 'none' or self.state == 'cancelled' or not self.date_start:
            return False
        nxt = self._next_start()
        if self.repeat_until and nxt > self.repeat_until:
            return False
        series = self.series_id or self
        if not self.id:
            return True
        return not self.search_count([('id', '!=', self.id), ('date_start', '>', self.date_start), '|',
                                      ('series_id', '=', series.id), ('id', '=', series.id)])

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for plan in self:
            if plan.date_end < plan.date_start:
                raise ValidationError(_('The campaign cannot end before it starts.'))

    @api.depends('recommendation_id')
    def _compute_brand_id(self):
        default = self.env['mi.brand'].browse(self.env.context.get('default_brand_id')).exists()
        for plan in self:
            plan.brand_id = plan.brand_id or plan.recommendation_id.brand_id or default

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._sync_channel_items()
        return plans

    def write(self, vals):
        result = super().write(vals)
        if 'channel_ids' in vals:
            self._sync_channel_items()
        return result

    def _sync_channel_items(self):
        """One line per chosen channel; lines for removed channels go unless a draft or to-do already exists."""
        for plan in self:
            wanted = set(plan.channel_ids.mapped('code'))
            existing = set(plan.item_ids.mapped('channel'))
            new = [(0, 0, {'channel': code}) for code in sorted(wanted - existing)]
            stale = plan.item_ids.filtered(lambda i: i.channel not in wanted and not i.res_id and not i.activity_done
                                           and not i.note)
            commands = new + [(2, item.id) for item in stale]
            if commands:
                super(Plan, plan).write({'item_ids': commands})

    @api.depends('status')
    def _compute_color(self):
        colors = {'brief': 0, 'content': 3, 'review': 2, 'scheduled': 4, 'live': 10, 'done': 7, 'cancelled': 1}
        for plan in self:
            plan.color = colors.get(plan.status, 0)

    # ------------------------------------------------------------------ status and progress

    @api.depends('state', 'item_ids.stage')
    def _compute_status(self):
        """Before and during the review the campaign stays in its step, whatever a channel app shows; after the
        approval it follows the channels (Scheduled until one is out, then Live)."""
        for plan in self:
            if plan.state in BEFORE_REVIEW + ('done', 'cancelled'):
                plan.status = plan.state
            elif 'out' in plan.item_ids.mapped('stage'):
                plan.status = 'live'
            else:
                plan.status = 'scheduled'

    @api.depends('item_ids.stage', 'review_request_id.state', 'date_start', 'date_end')
    def _compute_progress(self):
        today = fields.Date.context_today(self)
        for plan in self:
            counted = plan.item_ids.filtered(lambda i: i.stage != 'unavailable')
            plan.channel_count = len(counted)
            plan.channels_out = len(counted.filtered(lambda i: i.stage in ('out', 'todo_done')))
            waiting = plan._pending_requests().sudo().approver_ids.filtered(
                lambda line: line.status == 'submitted').user_id
            plan.waiting_for = ', '.join(waiting.mapped('name')) or False
            if not plan.date_start or not plan.date_end:
                plan.day_label = False
            elif today < plan.date_start:
                plan.day_label = _('Starts in %s day(s)', (plan.date_start - today).days)
            elif today > plan.date_end:
                plan.day_label = _('Ended %s', format_date(self.env, plan.date_end))
            else:
                plan.day_label = _('Day %(day)s of %(total)s', day=(today - plan.date_start).days + 1,
                                   total=(plan.date_end - plan.date_start).days + 1)

    def _app_requests(self):
        """Approval requests of the channel apps (Messaging, Social) for this campaign's drafts."""
        requests = self.env['approval.center.request']
        for item in self.item_ids:
            requests |= item._app_requests()
        return requests

    def _pending_requests(self):
        requests = (self.review_request_id | self._app_requests()).sudo()
        return requests.filtered(lambda r: r.state == 'submitted')

    def _my_reviews(self):
        """Requests of this campaign I can decide now (assigned, pending, and not my own unless allowed)."""
        user = self.env.user
        return self._pending_requests().filtered(
            lambda r: r.approver_ids.filtered(lambda line: line.user_id == user and line.status == 'submitted')
            and (r.requester_id != user or r.policy_id.allow_self_approval))

    @api.depends_context('uid')
    @api.depends('state', 'user_id', 'worker', 'item_ids.stage', 'review_request_id.state')
    def _compute_needs_me(self):
        for plan in self:
            mine = plan._my_reviews()
            plan.can_review = bool(mine)
            if plan.is_template:
                plan.next_step, plan.my_todo, plan.needs_me = _('Template: use it to start a campaign'), False, False
                continue
            step, owner_step = plan._next_step()
            plan.next_step = step
            if mine:
                plan.my_todo = _('Approve or refuse the campaign')
            elif plan.user_id == self.env.user and owner_step:
                plan.my_todo = step
            else:
                plan.my_todo = False
            plan.needs_me = bool(plan.my_todo)

    def _next_step(self):
        """(text, owner must act) for the campaign as it is now."""
        self.ensure_one()
        stages = self.item_ids.mapped('stage')
        fix = len([s for s in stages if s in ('blocked', 'failed')])
        if self.state == 'cancelled':
            return _('Cancelled'), False
        if self.state == 'done':
            return _('Finished'), False
        if self._ai_busy():
            return _('The AI assistant is writing the channels'), False
        if fix:
            return _('Fix %s channel(s): see Next step on each line', fix), True
        if self.state == 'brief':
            if not self.item_ids:
                return _('Choose the channels'), True
            return (_('Prepare the drafts') if self.worker == 'me' else _('Start the AI assistant')), True
        if self.state == 'content':
            return _('Finish the drafts, then send the campaign for review'), True
        if self.state == 'review':
            requests = self._pending_requests().sudo()
            approvers = requests.approver_ids.filtered(lambda line: line.status == 'submitted').user_id
            others = approvers - requests.requester_id
            if approvers and not others and not requests.policy_id.filtered('allow_self_approval'):
                return _('Nobody else can approve it: add another approver (Approvals › Configuration › '
                         'Marketing campaign) or allow self-approval there'), True
            return _('Waiting for approval by %s', ', '.join(approvers.mapped('name')) or '-'), False
        if self.state == 'scheduled':
            return _('Approved: goes out on %s', format_date(self.env, self.date_start)), False
        return _('Running until %s', format_date(self.env, self.date_end)), False

    def _search_needs_me(self, operator, value):
        if operator in ('in', 'not in') and len(value) == 1 and isinstance(next(iter(value)), bool):
            operator, value = ('=' if operator == 'in' else '!='), next(iter(value))
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search.'))
        plans = self.search([('state', 'in', ACTIVE), ('is_template', '=', False)]).filtered('needs_me')
        positive = (operator == '=') == value
        return [('id', 'in' if positive else 'not in', plans.ids)]

    def _sync_state(self):
        """Store the status the channels show and write the timeline: one note per channel change."""
        for plan in self:
            for item in plan.item_ids:
                if item.stage != item.last_stage:
                    if item.last_stage or item.stage not in ('not_started', 'unavailable'):
                        plan.message_post(body=item._timeline_text(), subtype_xmlid='mail.mt_note')
                    item.sudo().last_stage = item.stage
            plan.invalidate_recordset(['status'])
            if plan.state == 'review':
                refused = (plan.review_request_id | plan._app_requests()).sudo().filtered(
                    lambda r: r.state == 'refused')
                if refused:
                    plan._back_to_content(_('Refused: %s. Edit and send the campaign for review again.',
                                            ', '.join(refused.mapped('name'))))
                    continue
            if plan.state in ('scheduled', 'live') and plan.status != plan.state:
                plan.sudo().state = plan.status

    @api.depends('date_start', 'date_end', 'item_ids.channel', 'brand_id', 'state')
    def _compute_clash_note(self):
        """Other active plans of the brand on the same channel and dates: a fatigue warning, never a block."""
        for plan in self:
            plan.clash_note = False
            if not plan.id or plan.is_template or plan.state not in ACTIVE or not plan.date_start or not plan.date_end:
                continue
            channels = set(plan.item_ids.mapped('channel'))
            others = self.search([('id', '!=', plan.id), ('brand_id', '=', plan.brand_id.id), ('is_template', '=', False),
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
            raise UserError(_('Choose the suggestion first.'))
        start = fields.Date.context_today(self)
        lines = [option.problem, option.expected_result]
        plan = self.create({
            'name': option.name, 'recommendation_id': option.id, 'brand_id': option.brand_id.id,
            'budget': option.budget,
            'date_start': start, 'date_end': start + timedelta(days=max(option.duration_days or 14, 1) - 1),
            'message': '\n\n'.join(line.strip() for line in lines if line and line.strip()),
            'audience': option.audience, 'kpis': option.kpis,
            'channel_ids': [(6, 0, option.channel_ids.ids)],
        })
        plan.message_post(body=_('Campaign started from the suggestion “%s”.', option.name))
        return plan

    # ------------------------------------------------------------------ steps

    def action_prepare(self):
        """Create the tracking campaign and every missing draft (Content step)."""
        for plan in self:
            plan.check_access('write')
            if plan.is_template:
                raise UserError(_('This is a template: click “Use this template” to start a campaign from it.'))
            if plan.state not in ACTIVE:
                raise UserError(_('Only an active campaign can prepare drafts.'))
            if not plan.utm_campaign_id:
                plan.utm_campaign_id = self.env['utm.campaign'].sudo().create(
                    {'title': plan.name, 'user_id': plan.user_id.id}).id
            for item in plan.item_ids.filtered(lambda i: not i.res_id and not i.activity_done):
                item._prepare()
            if plan.state == 'brief':
                plan.state = 'content'
            plan._sync_state()
        return True

    def _campaign_policy(self):
        """The company's "Marketing campaign" approval type (created on first use, approvers set by a manager)."""
        self.ensure_one()
        Policy = self.env['approval.center.policy'].sudo().with_context(active_test=False)
        model = self.env['ir.model']._get('mi.plan')
        policy = Policy.search([('model_id', '=', model.id), ('action_name', '=', 'action_release'),
                                ('company_id', '=', self.company_id.id)], limit=1)
        if not policy:
            template = self.env.ref('marketing_intel_plan.policy_campaign', raise_if_not_found=False)
            policy = template.sudo().copy({'company_id': self.company_id.id, 'name': template.name}) \
                if template and template.company_id != self.company_id else template.sudo()
            if template and template.company_id != self.company_id:
                policy.company_id = self.company_id
        if not policy or not policy.active:
            raise UserError(_('Campaign reviews are switched off: activate the approval type “Marketing campaign”.'))
        return policy

    def action_submit_review(self):
        """Review step, all or nothing: every draft must exist and be accepted by its app's own approval (Messaging,
        Social); then one campaign request is opened for the approver. If a channel has a problem, nothing is
        submitted, each line says what to fix, and the campaign stays where it was."""
        problems = []
        for plan in self:
            plan.check_access('write')
            if plan.is_template:
                raise UserError(_('This is a template: click “Use this template” to start a campaign from it.'))
            if plan.state not in BEFORE_REVIEW:
                raise UserError(_('This campaign was already reviewed.'))
            plan.action_prepare()  # creates any missing draft, retries failed ones
            notes = {item: item.note for item in plan.item_ids.filtered(lambda i: not i.res_id and i.stage == 'blocked')}
            if not notes:
                try:
                    with self.env.cr.savepoint():
                        for item in plan.item_ids.filtered(lambda i: i.res_id and i.stage in ('draft', 'blocked')):
                            error = item._submit()
                            if error:
                                notes[item] = error
                        if notes:
                            raise _Problems()
                        plan._open_review_request()
                except _Problems:
                    pass
                except UserError as error:
                    problems.append('%s: %s' % (plan.name, error))
                    continue
            if notes:
                for item, note in notes.items():
                    item.note = note
                problems.append('%s:\n%s' % (plan.name, '\n'.join(
                    '• %s: %s' % (dict(CHANNELS)[item.channel], note) for item, note in notes.items())))
                continue
            plan.item_ids.filtered(lambda i: i.res_id).note = False
            plan.state = 'review'
            plan.message_post(body=_('Sent for review. %s', plan._next_step()[0]))
            plan._sync_state()
        if problems:
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'type': 'warning', 'sticky': True, 'title': _('Not sent for review yet'),
                'message': '\n\n'.join(problems),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}
        return True

    def _open_review_request(self):
        self.ensure_one()
        if self.review_request_id and self.review_request_id.state not in ('refused', 'cancelled'):
            return
        policy = self._campaign_policy()
        request = self.env['approval.center.request'].sudo().create({
            'name': _('Campaign: %(name)s (%(brand)s)', name=self.name, brand=self.brand_id.name),
            'policy_id': policy.id, 'company_id': self.company_id.id, 'requester_id': self.env.uid,
            'target_model': self._name, 'target_res_id': self.id, 'reason': self._review_summary(),
        })
        try:
            request.with_user(self.env.user).sudo().action_submit()
        except UserError as error:
            raise UserError(_('%(error)s Set who approves campaigns in Approvals › Configuration › '
                              '“Marketing campaign”.', error=str(error))) from None
        self.sudo().review_request_id = request

    def action_approve_review(self):
        """Approve everything in this campaign that waits for me: each channel's own approval, then the campaign."""
        self.ensure_one()
        mine = self._my_reviews()
        if not mine:
            raise UserError(_('Nothing in this campaign is waiting for your approval.'))
        campaign = mine.filtered(lambda r: r == self.review_request_id)
        for request in (mine - campaign) | campaign:
            request.with_user(self.env.user).sudo(False).action_approve()
        self.invalidate_recordset()
        self._sync_state()
        return True

    def action_refuse_review(self):
        self.ensure_one()
        mine = self._my_reviews()
        if not mine:
            raise UserError(_('Nothing in this campaign is waiting for your approval.'))
        for request in mine:
            request.with_user(self.env.user).sudo(False).action_refuse()
        self._back_to_content(_('Refused by %s. Edit the drafts and send the campaign for review again.',
                                self.env.user.name))
        return True

    def _back_to_content(self, note):
        for plan in self.filtered(lambda p: p.state == 'review'):
            plan.sudo().state = 'content'
            plan.message_post(body=note)

    def action_release(self):
        """After the campaign approval: schedule Email and SMS for the start day, publish events.
        Runs from the approval (as the requester); idempotent, and only with an approved campaign request."""
        for plan in self:
            request = plan.sudo().review_request_id
            if not request or request.state != 'approved':
                raise AccessError(_('This campaign has no approved campaign review.'))
            for item in plan.item_ids.filtered('res_id'):
                item._release()
            plan.sudo().state = 'scheduled'
            plan.message_post(body=_('Approved by %s. Email, SMS and events are scheduled; Messaging and Social go '
                                     'out as their own approvals allow.', request.approver_id.name or '-'))
            plan._sync_state()
        return True

    def _send_at(self):
        """Start day at SEND_HOUR in the owner's time zone, or a few minutes from now if that has passed."""
        try:
            zone = ZoneInfo(self.user_id.tz or 'UTC')
        except (KeyError, ValueError):
            zone = ZoneInfo('UTC')
        local = datetime.combine(self.date_start, time(SEND_HOUR, 0), tzinfo=zone)
        planned = local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
        return max(planned, fields.Datetime.now() + timedelta(minutes=5))

    def _review_summary(self):
        lines = [_('Brand: %s', self.brand_id.name), _('Dates: %(start)s to %(end)s', start=self.date_start,
                                                       end=self.date_end)]
        if self.budget:
            lines.append(_('Budget: %(amount)s %(currency)s', amount=self.budget, currency=self.currency_id.name))
        if self.goal_id:
            lines.append(_('Goal: %s', self.goal_id.name))
        for item in self.item_ids:
            lines.append('— %s: %s' % (dict(CHANNELS)[item.channel], (item.preview or '').strip()[:300] or '-'))
        return '\n'.join(lines)

    # ------------------------------------------------------------------ reuse

    def _copy_values(self, **overrides):
        """A new campaign like this one: brief, channels and each channel's text; new drafts, new review."""
        self.ensure_one()
        duration = (self.date_end - self.date_start).days if self.date_start and self.date_end else 29
        start = overrides.pop('date_start', None) or fields.Date.context_today(self)
        lines = []
        for item in self.item_ids:
            subject, text = item._content()
            lines.append((0, 0, {'channel': item.channel, 'content_subject': subject, 'content_text': text}))
        values = {
            'name': self.name, 'brand_id': self.brand_id.id, 'goal_id': self.goal_id.id, 'budget': self.budget,
            'message': self.message, 'audience': self.audience, 'kpis': self.kpis, 'worker': self.worker,
            'user_id': self.env.user.id, 'date_start': start, 'date_end': start + timedelta(days=max(duration, 0)),
            'channel_ids': [(6, 0, self.channel_ids.ids)], 'item_ids': lines,
        }
        values.update(overrides)
        return values

    def _open_form(self, name=None):
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan', 'res_id': self.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current', 'name': name or self.name}

    def action_duplicate(self):
        """Duplicate & edit: same channels and texts, today's dates, ready to change."""
        self.ensure_one()
        family = self._own_template()
        copy = self.create(self._copy_values(name=_('%s (copy)', self.name), worker='me', template_id=family.id))
        copy.message_post(body=_('Copied from “%s”.', self.name))
        return copy._open_form()

    def action_save_template(self):
        """One template per campaign family: a campaign, its copies and the campaigns started from its template all
        update the same template. A new template may not take the name of another template of the brand."""
        self.ensure_one()
        if self.is_template:
            raise UserError(_('This is already a template.'))
        values = self._copy_values(is_template=True, worker='me', repeat='none', template_source_id=self.id)
        template = self._own_template()
        if template:
            values['item_ids'] = [(5, 0, 0)] + values['item_ids']
            for name in ('date_start', 'date_end', 'user_id', 'template_source_id', 'name', 'brand_id'):
                values.pop(name, None)
            template.write(values)
            template.message_post(body=_('Template updated from “%s”.', self.name))
        else:
            same = self.search([('is_template', '=', True), ('brand_id', '=', self.brand_id.id),
                                ('name', '=ilike', self.name)], limit=1)
            if same:
                raise UserError(_('%(brand)s already has a template called “%(name)s”. Use that template (Campaigns › '
                                  'Templates), or rename this campaign before saving it as a new template.',
                                  brand=self.brand_id.name, name=self.name))
            template = self.create(values)
            template.message_post(body=_('Template saved from “%s”.', self.name))
        return template._open_form()

    def action_use_template(self):
        self.ensure_one()
        if not self.is_template:
            raise UserError(_('This campaign is not a template.'))
        brand = self.env['mi.brand'].browse(self.env.context.get('default_brand_id')).exists() or self.brand_id
        plan = self.create(self._copy_values(is_template=False, template_id=self.id, brand_id=brand.id,
                                             repeat=self.repeat, repeat_until=False))
        plan.message_post(body=_('Started from the template “%s”.', self.name))
        return plan._open_form()

    @api.model
    def _cron_repeat(self, lead_days=3):
        """Create the next run of each repeating series a few days before it starts and send it for review."""
        today = fields.Date.context_today(self)
        for plan in self.search([('repeat', '!=', 'none'), ('is_template', '=', False),
                                 ('state', '!=', 'cancelled')]):
            if not plan._repeats_next():
                continue
            start = plan._next_start()
            if start - timedelta(days=lead_days) > today:
                continue
            owner = plan.user_id
            try:
                with self.env.cr.savepoint():
                    run = plan.with_user(owner).with_context(allowed_company_ids=[plan.company_id.id])._repeat_run(
                        start)
                    plan.message_post(body=_('Next run created: %s', run._get_html_link()))
            except (AccessError, UserError, ValidationError) as error:
                plan.message_post(body=_('The next run could not be created: %s', error))
                plan.activity_schedule('mail.mail_activity_data_todo', user_id=owner.id,
                                       summary=_('Next run of the campaign not created'), note=str(error))

    def _repeat_run(self, start):
        self.ensure_one()
        run = self.create(self._copy_values(date_start=start, series_id=(self.series_id or self).id,
                                            repeat=self.repeat, repeat_until=self.repeat_until))
        if run.worker == 'me':
            run.action_submit_review()  # quick review; problems are left on the lines for the owner
        return run

    def action_done(self):
        plans = self.filtered(lambda p: p.state in ACTIVE)
        plans.state = 'done'
        plans._on_done()
        return True

    def _on_done(self):
        """Hook: the AI assistant writes what we learned."""
        return True

    def _ai_busy(self):
        """Hook: True while the AI assistant is writing this campaign."""
        return False

    @api.model
    def _cron_close_finished(self):
        plans = self.search([('state', 'in', ('scheduled', 'live')), ('date_end', '<', fields.Date.today())])
        for plan in plans:
            plan.message_post(body=_('The end date has passed: campaign closed automatically.'))
        plans.action_done()

    def action_cancel(self):
        """Cancelling does not touch what already went out: withdraw or cancel those in their apps."""
        for plan in self.filtered(lambda p: p.state in ACTIVE):
            if plan.review_request_id.state == 'submitted':
                plan.review_request_id.with_user(plan.review_request_id.requester_id).sudo().action_cancel()
            plan.state = 'cancelled'
        return True

    def action_reset(self):
        self.filtered(lambda p: p.state == 'cancelled').write({'state': 'brief', 'review_request_id': False})
        return True

    # ------------------------------------------------------------------ texts

    def _plain(self, limit=None):
        text = (self.message or self.name or '').strip()
        return text[:limit].rstrip() if limit else text

    def _html(self):
        parts = [Markup('<h2>%s</h2>') % self.name]
        parts += [Markup('<p>%s</p>') % escape(p).replace('\n', Markup('<br/>'))
                  for p in self._plain().split('\n\n') if p.strip()]
        parts.append(Markup('<p><em>%s</em></p>') % _('Draft from a campaign: rewrite before sending.'))
        return Markup('').join(parts)

    def _reason(self):
        return _('Campaign plan “%(plan)s” (%(start)s to %(end)s). KPIs: %(kpis)s',
                 plan=self.name, start=self.date_start, end=self.date_end,
                 kpis=' / '.join((self.kpis or '-').splitlines()))


class PlanItem(models.Model):
    _name = 'mi.plan.item'
    _description = 'Campaign channel'
    _order = 'plan_id, id'

    plan_id = fields.Many2one('mi.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    channel = fields.Selection(CHANNELS, required=True)
    res_model = fields.Char(readonly=True, string='Created in')
    res_id = fields.Many2oneReference(model_field='res_model', readonly=True)
    draft_name = fields.Char(compute='_compute_draft', string='Draft')
    draft_status = fields.Char(compute='_compute_draft', string='In its app')
    stage = fields.Selection(ITEM_STAGES, compute='_compute_draft', string='Status')
    next_step = fields.Char(compute='_compute_draft', string='Next step')
    preview = fields.Text(compute='_compute_draft', string='Content')
    last_stage = fields.Char(readonly=True, copy=False)
    app = fields.Char(compute='_compute_app', string='App')
    available = fields.Boolean(compute='_compute_app')
    activity_done = fields.Boolean(string='Done', help='For channels without an app: tick when it is ready.')
    note = fields.Char(readonly=True)
    content_subject = fields.Char(string='Saved subject', copy=False,
                                  help='Text kept from a copied campaign or template; written into the new draft.')
    content_text = fields.Text(string='Saved text', copy=False)
    live = fields.Boolean(compute='_compute_draft', string='Out',
                          help='Sent, scheduled or published in its app (not a draft or waiting for approval).')

    @api.depends('channel')
    def _compute_app(self):
        for item in self:
            target = TARGETS.get(item.channel)
            item.app = target[1] if target else _('To-do on the campaign')
            item.available = not target or target[0] in self.env

    @api.depends('res_model', 'res_id', 'activity_done', 'note', 'plan_id.state')
    def _compute_draft(self):
        for item in self:
            # Shown read-only to everyone who can read the campaign (an approver reads what they approve);
            # opening or changing the draft still needs that app's own rights.
            record = item._record()
            record = record.sudo() if record else record
            item.draft_name = record.display_name if record else False
            item.draft_status = item._app_status(record) if record else False
            stage = item._stage(record)
            if stage in ('draft', 'not_started') and item.plan_id._ai_busy():
                stage = 'writing'
            item.stage = stage
            item.next_step = item._item_next_step(record)
            item.live = item.stage in ('scheduled', 'out')
            item.preview = item._preview(record) if record else False

    @staticmethod
    def _app_status(record):
        field = record._fields.get('state') or record._fields.get('stage_id')
        if not field:
            return _('Created')
        value = record[field.name]
        if field.type == 'selection':
            return dict(field._description_selection(record.env)).get(value, value)
        return value.display_name

    def _stage(self, record):
        """One status vocabulary for every app."""
        if not record:
            if not TARGETS.get(self.channel):
                return 'todo_done' if self.activity_done else 'todo'
            if not self.available:
                return 'unavailable'
            if self.note:
                return 'blocked'
            return 'not_started'
        record = record.sudo()
        now = fields.Datetime.now()
        name = record._name
        draft = 'blocked' if self.note else 'draft'
        if name == 'mailing.mailing':
            if record.state == 'draft':
                return 'needs_review' if self.plan_id.state == 'review' else draft
            if record.state == 'in_queue' and record.schedule_date and record.schedule_date > now:
                return 'scheduled'
            if record.state == 'done' and not record.sent:
                return 'failed'
            return 'out'
        if name == 'mm.mailing':
            if record.state == 'draft':
                return draft
            if record.state == 'pending':
                return 'needs_review'
            if record.state == 'approved':
                later = record.schedule == 'later' and record.scheduled_at and record.scheduled_at > now
                return 'scheduled' if later else 'approved'
            if record.state == 'done' and not record.sent_count:
                return 'failed'
            if record.state in ('sending', 'done'):
                return 'out'
            return 'failed'
        if name == 'omni.social.campaign':
            if record.state == 'draft':
                return draft
            if record.state == 'review':
                return 'needs_review'
            if record.state == 'approved':
                return 'scheduled' if record.scheduled_at and record.scheduled_at > now else 'approved'
            if record.state == 'done':
                return 'out'
            return 'failed'
        if name == 'event.event':
            if self._event_published(record):
                return 'out'
            return 'needs_review' if self.plan_id.state == 'review' else draft
        return draft

    @staticmethod
    def _event_published(event):
        if 'is_published' in event._fields:
            return bool(event.is_published)
        return bool(event.stage_id) and event.stage_id != event._get_default_stage_id()

    def _preview(self, record):
        """What the approver reads: the text that goes out, in plain words."""
        record = record.sudo()
        if record._name == 'mailing.mailing':
            if record.mailing_type == 'sms':
                return record.body_plaintext or ''
            return '%s\n\n%s' % (record.subject or '', html2plaintext(record.body_html or ''))
        if record._name == 'mm.mailing':
            return record.body or ''
        if record._name == 'omni.social.campaign':
            versions = record.publication_ids.filtered(lambda p: p.state != 'cancelled')
            if versions:
                return '\n\n'.join('%s: %s' % (v.connection_id.name, v.body or '') for v in versions)
            return record.brief or ''
        if record._name == 'event.event':
            text = html2plaintext(record.description or '') if 'description' in record._fields else ''
            return '%s\n%s' % (record.name, text)
        return record.display_name

    def _content(self):
        """(subject, text) of this channel: from its draft, or what was saved on the line."""
        record = self._record()
        if not record:
            return self.content_subject or False, self.content_text or False
        record = record.sudo()
        if record._name == 'mailing.mailing':
            if record.mailing_type == 'sms':
                return False, record.body_plaintext
            return record.subject, html2plaintext(record.body_html or '')
        if record._name == 'mm.mailing':
            return False, record.body
        if record._name == 'omni.social.campaign':
            return False, record.brief
        if record._name == 'event.event':
            return record.name, html2plaintext(record.description or '') if 'description' in record._fields else False
        return False, False

    def _fill(self, subject=None, text=None):
        """Write a subject/text into the draft while it is still a draft. Returns an error or None."""
        record = self._record()
        if not record or self.stage not in ('draft', 'blocked', 'writing', 'not_started') or not (subject or text):
            return None
        try:
            with self.env.cr.savepoint():
                if record._name == 'mailing.mailing' and record.mailing_type == 'mail':
                    values = {'subject': subject} if subject else {}
                    if text:
                        html = text_to_html(text)
                        values.update({'body_html': html, 'body_arch': html})
                    record.write(values)
                elif record._name == 'mailing.mailing' and text:
                    record.write({'body_plaintext': text})
                elif record._name == 'mm.mailing' and text:
                    record.write({'body': text})
                elif record._name == 'omni.social.campaign' and text:
                    record.write({'brief': text})
                    record.publication_ids.filtered(lambda p: p.state == 'draft').write({'body': text})
                elif record._name == 'event.event':
                    values = {'name': subject} if subject else {}
                    if text and 'description' in record._fields:
                        values['description'] = text_to_html(text)
                    record.write(values)
        except (AccessError, UserError, ValidationError) as error:
            return str(error).splitlines()[0][:200]
        return None

    def _app_requests(self):
        record = self._record()
        if not record:
            return self.env['approval.center.request']
        record = record.sudo()
        if record._name == 'mm.mailing':
            return record.approval_request_id
        if record._name == 'omni.social.campaign':
            return record.publication_ids.approval_request_id
        return self.env['approval.center.request']

    def _item_next_step(self, record):
        """One plain sentence: what happens next on this channel, and who does it."""
        app = self.app
        stage = self.stage
        plan = self.plan_id
        if stage == 'unavailable':
            return _('Install %s to use this channel', app)
        if stage == 'todo':
            return _('To-do for %s: switch Done on when it is ready', plan.user_id.name)
        if stage == 'todo_done':
            return _('Done')
        if stage == 'not_started':
            return _('Created when the drafts are prepared')
        if stage == 'writing':
            return _('The AI assistant is writing it')
        if stage in ('blocked', 'failed') and self.note:
            return self.note
        record = record.sudo()
        when = self._planned_at(record)
        when = fields.Datetime.context_timestamp(self, when).strftime('%d %b %H:%M') if when else False
        if stage == 'draft':
            return _('Write it in %s (Open), then send the campaign for review', app)
        if stage == 'needs_review':
            approvers = (self._app_requests() or plan.review_request_id).sudo().filtered(
                lambda r: r.state == 'submitted').approver_ids.filtered(lambda l: l.status == 'submitted').user_id
            return _('Waiting for approval by %s', ', '.join(approvers.mapped('name')) or '-')
        if stage == 'approved':
            return _('Approved: %s sends it', app)
        if stage == 'scheduled':
            return _('Goes out on %s', when) if when else _('Scheduled')
        if stage == 'out':
            if plan.state in BEFORE_REVIEW:
                return _('Sent from %s before the campaign review', app)
            sent = self.result_sent
            if sent:
                return _('Sent to %s', sent)
            return _('Published') if record._name in ('omni.social.campaign', 'event.event') else _('Sent')
        if stage == 'failed':
            if record._name in ('mailing.mailing', 'mm.mailing') and record.state == 'done':
                return _('Sent to nobody: the lists had no one who can receive it')
            return _('Stopped in %(app)s (%(status)s): open it to see why', app=app, status=self.draft_status)
        return False

    @staticmethod
    def _planned_at(record):
        if record._name == 'mailing.mailing':
            return record.schedule_date
        if record._name in ('mm.mailing', 'omni.social.campaign'):
            return record.scheduled_at
        if record._name == 'event.event':
            return record.date_begin
        return False

    def _readiness(self, record):
        """What would stop this draft in its app, said with where to fix it (None when ready)."""
        accounts = _('Brand › Settings › Channels & accounts')
        if record._name == 'mailing.mailing':
            if not record.contact_list_ids:
                return _('Choose the mailing lists to send to (%s, or open the draft).', accounts)
            if record.mailing_type == 'mail' and not record.subject:
                return _('Write the email subject.')
            if record.mailing_type == 'sms' and not (record.body_plaintext or '').strip():
                return _('Write the SMS text.')
        elif record._name == 'mm.mailing':
            if not record.channel_id:
                return _('Choose the Messaging channel to send from (%s, or open the draft).', accounts)
            if not record.list_ids:
                return _('Choose the Messaging lists to send to (%s, or open the draft).', accounts)
        elif record._name == 'omni.social.campaign':
            if not record.connection_ids:
                return _('Choose the social pages to post to (%s, or open the draft).', accounts)
        return None

    def _submit(self):
        """Check the draft and submit it to its app's own approval (Messaging, Social). Email, SMS and Events wait
        for the campaign approval. Returns what to fix, or None."""
        self.ensure_one()
        record = self._record()
        problem = self._readiness(record)
        if problem:
            return problem
        try:
            with self.env.cr.savepoint():
                if record._name == 'mm.mailing':
                    if not (record.reason or '').strip():
                        record.reason = self.plan_id._reason()
                    record.action_submit()
                elif record._name == 'omni.social.campaign':
                    if record.missing_versions:
                        record.action_create_versions()
                    record.action_submit_all()
        except (AccessError, UserError, ValidationError) as error:
            return str(error).splitlines()[0][:250]
        return None

    def _release(self):
        """After the campaign approval: Email/SMS are queued for the start day; events are published."""
        self.ensure_one()
        record = self._record()
        try:
            with self.env.cr.savepoint():
                if record._name == 'mailing.mailing' and record.state == 'draft':
                    record.write({'schedule_type': 'scheduled', 'schedule_date': self.plan_id._send_at()})
                    record.action_put_in_queue()
                elif record._name == 'event.event' and not self._event_published(record):
                    if 'is_published' in record._fields:
                        record.is_published = True
                    else:
                        stage = self.env['event.stage'].search([('pipe_end', '=', False)], order='sequence desc',
                                                               limit=1)
                        if stage:
                            record.stage_id = stage
            self.note = False
        except (AccessError, UserError, ValidationError) as error:
            self.note = _('Not scheduled: %s', str(error).splitlines()[0][:200])

    def _timeline_text(self):
        label = dict(CHANNELS)[self.channel]
        stage = dict(ITEM_STAGES).get(self.stage, self.stage)
        text = _('%(channel)s: %(stage)s', channel=label, stage=stage)
        if self.note and self.stage in ('failed', 'blocked'):
            text += ' — ' + self.note
        return text

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
        if self.content_subject or self.content_text:
            error = self._fill(self.content_subject, self.content_text)
            if error:
                self.note = _('Saved text not used: %s', error)
        if hasattr(record, 'message_post'):
            record.message_post(body=_('Draft created from the campaign “%s”. It goes out after the campaign review.',
                                       plan.name))

    # One method per channel: drafts only, with the person's permissions.

    def _brand_accounts(self, plan, model, what):
        """The brand's own accounts of one kind. With several brands in the company, a missing account stops
        the draft (never another brand's account); a company with a single brand uses the app's defaults."""
        accounts = plan.brand_id._accounts(model)
        if accounts:
            return accounts
        brands = self.env['mi.brand'].sudo().search_count([('company_id', '=', plan.company_id.id)])
        if brands > 1:
            raise UserError(_('Set the %(what)s of “%(brand)s” in Brand › Settings › Channels & accounts.',
                              what=what, brand=plan.brand_id.name))
        return self.env[model]

    def _draft_social(self, plan):
        connections = self._brand_accounts(plan, 'omni.social.connection', _('Social pages'))
        values = {'name': plan.name, 'brief': plan._plain(2000), 'reason': plan._reason(),
                  'scheduled_at': datetime.combine(plan.date_start, time(2, 0))}
        if connections:
            values.update({'purpose_id': connections[0].purpose_id.id,
                           'connection_ids': [(6, 0, connections.filtered(
                               lambda c: c.purpose_id == connections[0].purpose_id).ids)]})
        return self.env['omni.social.campaign'].create(values)

    def _draft_messaging(self, plan):
        channels = self._brand_accounts(plan, 'omni.channel', _('Messaging channel'))
        values = {'name': plan.name, 'body': plan._plain(900), 'reason': plan._reason(),
                  'utm_campaign_id': plan.utm_campaign_id.id}
        if channels:
            channel = channels[0]
            values.update({'channel_id': channel.id, 'purpose_id': channel.purpose_id.id,
                           'channel': channel.channel_type_id.code})
            lists = plan.brand_id._accounts('mm.list') or self.env['mm.list']
            lists = lists.filtered(lambda l: l.purpose_id == channel.purpose_id)
            if lists:
                values['list_ids'] = [(6, 0, lists.ids)]
        return self.env['mm.mailing'].create(values)

    def _mailing_values(self, plan, mailing_type):
        lists = self._brand_accounts(plan, 'mailing.list', _('mailing lists'))
        values = {'subject': plan.name, 'mailing_type': mailing_type, 'campaign_id': plan.utm_campaign_id.id,
                  'user_id': plan.user_id.id}
        if lists:
            values['contact_list_ids'] = [(6, 0, lists.ids)]
        if mailing_type == 'mail' and plan.brand_id.email_from:
            values['email_from'] = plan.brand_id.email_from
        return values

    def _draft_email(self, plan):
        values = self._mailing_values(plan, 'mail')
        values.update({'body_html': plan._html(), 'body_arch': plan._html()})
        return self.env['mailing.mailing'].create(values)

    def _draft_sms(self, plan):
        values = self._mailing_values(plan, 'sms')
        values['body_plaintext'] = plan._plain(160)
        return self.env['mailing.mailing'].create(values)

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
            raise UserError(_('This draft no longer exists.'))
        try:
            record.check_access('read')
        except AccessError:
            raise UserError(_('You need access to %s to open this draft. Its text is on the Review tab.',
                              self.app)) from None
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

    def action_use_idea(self):
        """Choose this suggestion and start a campaign from it in one step."""
        self.ensure_one()
        if self.state == 'rejected':
            raise UserError(_('This suggestion was rejected. Reset it to proposed first.'))
        if self.state == 'proposed':
            self.action_choose()
        return self.action_create_plan()

    def action_open_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.plan', 'name': _('Campaigns'),
                'view_mode': 'list,form', 'domain': [('recommendation_id', '=', self.id)]}
