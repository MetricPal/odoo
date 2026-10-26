"""Marketing workflows: when something happens, do something — approved once, then automatic.

A workflow is a trigger and a few steps. A manager approves the workflow, its
exact message text and its limits once (Approval Center). After that the
workflow runs on its own:

* new events are read every few minutes (comments and private messages on
  social media, event registrations, email clicks, new leads), only those that
  happened after the workflow started;
* each person is handled once per workflow; messages go only to known contacts
  with a current opt-in on that channel, at most ``daily_cap`` per day across
  all workflows; everyone skipped gets a reason in the run log;
* messages are queued through Omnichannel with the workflow's approval as their
  evidence; the dispatch worker re-checks the approval, the channel and the
  person's opt-in right before sending.

Any change to an approved workflow pauses it until it is approved again.

Note: social platforms do not tell apps who *liked* a post, only how many; the
usual equivalent is "comment a keyword", which is supported.
"""

import hashlib
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError

_logger = logging.getLogger(__name__)

TRIGGERS = [
    ('social_comment', 'Someone comments on a post'),
    ('social_message', 'Someone sends us a private message'),
    ('event_registration', 'Someone registers for an event'),
    ('email_click', 'Someone clicks a link in an email'),
    ('lead', 'A new lead comes from a campaign'),
    ('form_submit', 'Someone submits a form'),
]
ACTIONS = [
    ('message', 'Send a WhatsApp / Telegram message'),
    ('email', 'Send an email'),
    ('sms', 'Send an SMS'),
    ('split', 'Split the audience'),
    ('add_list', 'Add them to a Messaging list'),
    ('lead', 'Create a lead'),
    ('todo', 'Create a to-do for the owner'),
]
SENDS = ('message', 'email', 'sms')
STEP_COPY = ('sequence', 'action', 'message', 'note', 'path', 'subject', 'split_by', 'split_question', 'split_words',
             'split_score')
PATHS = [('all', 'Everyone'), ('a', 'Path A'), ('b', 'Path B')]
SPLITS = [('ai', 'AI decides'), ('words', 'Words in what they wrote'), ('score', 'Lead score')]
FORMS = [('lead', 'Website contact form (creates a lead)'), ('newsletter', 'Newsletter sign-up')]
FROZEN = {'trigger', 'keyword', 'plan_id', 'connection_ids', 'channel_id', 'daily_cap', 'once_per_person',
          'brand_id', 'form_kind', 'mailing_list_id', 'path_a_name', 'path_b_name'}
BATCH = 200
RECIPE_ICONS = [('social_comment', 'forum'), ('social_message', 'mail'), ('event_registration', 'event_available'),
                ('email_click', 'mouse'), ('lead', 'person_add'), ('form_submit', 'list_alt')]
AI_SPLIT_PROMPT = (
    'You sort one person into Path A or Path B for a marketing workflow.\n'
    'Path A: %(a)s. Path B: %(b)s.\nWhat counts as Path A: %(rule)s\n'
    'Answer with ONE JSON object and nothing else: {"path": "a" or "b", "reason": "one short sentence"}.\n'
    'What the person wrote or filled in:\n%(text)s'
)


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _handle(value):
    return (value or '').strip().lstrip('@').casefold()


class Flow(models.Model):
    _name = 'mi.flow'
    _description = 'Marketing workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mi.owner.activity.mixin']
    _order = 'state, name, id'

    name = fields.Char(required=True, tracking=True, string='Workflow')
    brand_id = fields.Many2one('mi.brand', required=True, index=True, tracking=True,
                               default=lambda self: self.env['mi.brand'].browse(
                                   self.env.context.get('default_brand_id')).exists())
    company_id = fields.Many2one(related='brand_id.company_id', store=True)
    user_id = fields.Many2one('res.users', string='Owner', default=lambda self: self.env.user, required=True)
    state = fields.Selection([('draft', 'Draft'), ('pending', 'Waiting for approval'), ('active', 'Running'),
                              ('paused', 'Paused')], default='draft', required=True, readonly=True, tracking=True,
                             copy=False, group_expand=True, string='Status')
    trigger = fields.Selection(TRIGGERS, required=True, default='social_comment', string='When')
    keyword = fields.Char(help='Only when the comment or message contains this word (any case). Empty: all.')
    plan_id = fields.Many2one('mi.plan', string='Campaign', domain="[('brand_id', '=', brand_id), "
                                                                 "('is_template', '=', False)]",
                              help='Comments: only on this campaign\'s posts. Events, clicks and leads: this '
                                   'campaign\'s event, emails or tracking campaign.')
    connection_ids = fields.Many2many('omni.social.connection', string='Social pages',
                                      help='Empty: the brand\'s own social pages (Brand › Settings › Channels & '
                                           'accounts).')
    channel_id = fields.Many2one('omni.channel', string='Send messages from',
                                 domain="[('company_id', '=', company_id), "
                                        "('channel_type_id.code', 'in', ('whatsapp', 'telegram'))]",
                                 help='The WhatsApp number or Telegram bot. Empty: the brand\'s Messaging channel.')
    once_per_person = fields.Boolean(default=True, string='Once per person',
                                     help='Each person goes through this workflow only once.')
    daily_cap = fields.Integer(default=1, string='Messages per person per day',
                               help='At most this many workflow messages to one person per day, across all '
                                    'workflows.')
    form_kind = fields.Selection(FORMS, default='lead', string='Form',
                                 help='Contact form: website forms that create a lead. Newsletter: sign-ups to a '
                                      'mailing list.')
    mailing_list_id = fields.Many2one('mailing.list', string='Mailing list',
                                      help='Newsletter sign-ups to this list only. Empty: any list.')
    path_a_name = fields.Char(default=lambda self: _('High intent'), string='Path A is',
                              help='Name of Path A after a split, e.g. High intent.')
    path_b_name = fields.Char(default=lambda self: _('Low intent'), string='Path B is')
    has_split = fields.Boolean(compute='_compute_has_split')
    step_ids = fields.One2many('mi.flow.step', 'flow_id', string='Then', copy=True)
    run_ids = fields.One2many('mi.flow.run', 'flow_id', string='Runs')
    summary = fields.Char(compute='_compute_summary', string='What it does')
    requester_id = fields.Many2one('res.users', readonly=True, copy=False, string='Asked by')
    approval_request_id = fields.Many2one('approval.center.request', readonly=True, copy=False,
                                          string='Approval')
    approved_digest = fields.Char(readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    last_seen_id = fields.Integer(readonly=True, copy=False)
    last_checked = fields.Datetime(readonly=True, copy=False)
    runs_today = fields.Integer(compute='_compute_stats', string='Today')
    sent_today = fields.Integer(compute='_compute_stats', string='Messages today')
    skipped_today = fields.Integer(compute='_compute_stats', string='Skipped today')
    failed_today = fields.Integer(compute='_compute_stats', string='Errors today')
    run_count = fields.Integer(compute='_compute_stats', string='Runs')
    changed = fields.Boolean(compute='_compute_changed', string='Changed since approval')

    # ------------------------------------------------------------------ display

    @api.depends('step_ids.action')
    def _compute_has_split(self):
        for flow in self:
            flow.has_split = any(step.action == 'split' for step in flow.step_ids)

    @api.depends('trigger', 'keyword', 'step_ids.action', 'plan_id')
    def _compute_summary(self):
        triggers, actions = dict(TRIGGERS), dict(ACTIONS)
        def low(text):
            return text[:1].lower() + text[1:]
        for flow in self:
            when = low(triggers.get(flow.trigger, ''))
            if flow.keyword:
                when += _(' with “%s”', flow.keyword)
            steps = ', '.join(low(actions[s.action]) for s in flow.step_ids.sorted('sequence')) or '…'
            flow.summary = _('When %(when)s → %(steps)s', when=when, steps=steps)

    def _compute_stats(self):
        start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        Run = self.env['mi.flow.run'].sudo()
        for flow in self:
            runs = Run.search([('flow_id', '=', flow.id), ('create_date', '>=', start)])
            flow.runs_today = len(runs)
            flow.sent_today = sum(runs.mapped('message_count'))
            flow.skipped_today = len(runs.filtered(lambda r: r.state == 'skipped'))
            flow.failed_today = len(runs.filtered(lambda r: r.state == 'failed'))
            flow.run_count = Run.search_count([('flow_id', '=', flow.id)])

    @api.depends('approved_digest')
    def _compute_changed(self):
        for flow in self:
            flow.changed = bool(flow.approved_digest) and flow._digest() != flow.approved_digest

    # ------------------------------------------------------------------ frozen content

    def _payload(self):
        self.ensure_one()
        return {
            'brand': self.brand_id.id, 'trigger': self.trigger, 'keyword': (self.keyword or '').strip(),
            'plan': self.plan_id.id, 'connections': sorted(self.connection_ids.ids), 'channel': self.channel_id.id,
            'once': self.once_per_person, 'cap': self.daily_cap,
            'steps': [[s.action, (s.message or '').strip(), s.list_id.id, (s.note or '').strip()]
                      + ([s.path, (s.subject or '').strip(), s.split_by or '', (s.split_words or '').strip(),
                          s.split_score, (s.split_question or '').strip()]
                         if s.action in ('email', 'sms', 'split') or s.path != 'all' else [])
                      for s in self.step_ids.sorted(lambda s: (s.sequence, s.id))],
            **({'form': self.form_kind, 'list': self.mailing_list_id.id} if self.trigger == 'form_submit' else {}),
            **({'paths': [self.path_a_name or '', self.path_b_name or '']} if self.has_split else {}),
        }

    def _digest(self):
        return _digest(self._payload())

    def write(self, vals):
        result = super().write(vals)
        if FROZEN & vals.keys():
            self._changed_after_approval()
        if 'state' in vals or 'user_id' in vals:
            self._sync_owner_activity()
        return result

    def action_new_from_recipe(self):
        """New workflow: pick a recipe (or start from scratch there)."""
        action = self.env['ir.actions.act_window']._for_xml_id('marketing_intel_flow.action_recipe_pick')
        action['context'] = {k: v for k, v in self.env.context.items() if k == 'default_brand_id'}
        return action

    def _owner_step(self):
        self.ensure_one()
        if self.state == 'paused' and self.changed:
            return _('Ask approval again for the changed workflow'), self.user_id
        if self.state == 'draft' and self.approval_request_id.state == 'refused':
            return _('The approval was refused: change the workflow and ask again'), self.user_id
        return False, False

    def _changed_after_approval(self):
        for flow in self.filtered(lambda f: f.state in ('active', 'pending')):
            if flow.state == 'pending' and flow.approval_request_id.state == 'submitted':
                flow.approval_request_id.with_user(flow.requester_id).sudo().action_cancel()
            flow.sudo().state = 'paused' if flow.approved_digest else 'draft'
            flow.message_post(body=_('Changed: it waits for a new approval before it runs again.'))

    # ------------------------------------------------------------------ setup

    def _connections(self):
        self.ensure_one()
        return self.connection_ids or self.brand_id._accounts('omni.social.connection') or \
            self.env['omni.social.connection']

    def _channel(self):
        self.ensure_one()
        return self.channel_id or self.brand_id._accounts('omni.channel').filtered(
            lambda c: c.channel_type_id.code in ('whatsapp', 'telegram'))[:1]

    def _problems(self):
        """What must be fixed before the workflow can be approved."""
        self.ensure_one()
        problems = []
        if not self.step_ids:
            problems.append(_('Add at least one step under “Then”.'))
        if self.trigger in ('social_comment', 'social_message') and not self._connections():
            problems.append(_('Choose the social pages to watch (or set them in the brand’s Channels & accounts).'))
        if self.trigger in ('event_registration', 'email_click', 'lead') and not self.plan_id:
            problems.append(_('Choose the campaign whose event, emails or leads it watches.'))
        if self.trigger == 'lead' and 'crm.lead' not in self.env:
            problems.append(_('Install CRM to watch leads.'))
        if self.trigger == 'form_submit' and self.form_kind == 'lead' and 'crm.lead' not in self.env:
            problems.append(_('Install CRM: website contact forms create leads.'))
        problems += self._path_problems()
        for step in self.step_ids:
            if step.action == 'message':
                channel = self._channel().sudo()
                if not (step.message or '').strip():
                    problems.append(_('Write the message to send.'))
                if not channel:
                    problems.append(_('Choose the WhatsApp or Telegram channel to send from.'))
                elif not channel.approval_type_id:
                    problems.append(_('The channel has no message approval type: an Omnichannel administrator '
                                      'chooses one.'))
                elif not channel.selected_sender_id or channel.selected_sender_id.health != 'healthy':
                    problems.append(_('The channel has no verified sender: an Omnichannel administrator checks '
                                      'one.'))
            if step.action == 'email' and not ((step.subject or '').strip() and (step.message or '').strip()):
                problems.append(_('Write the email subject and text.'))
            if step.action == 'sms' and not (step.message or '').strip():
                problems.append(_('Write the SMS text.'))
            if step.action == 'sms' and 'sms.sms' not in self.env:
                problems.append(_('Install SMS to send text messages.'))
            if step.action == 'add_list' and not step.list_id:
                problems.append(_('Choose the list to add people to.'))
            if step.action == 'lead' and 'crm.lead' not in self.env:
                problems.append(_('Install CRM to create leads.'))
        return list(dict.fromkeys(problems))

    def _path_problems(self):
        steps = self.step_ids.sorted(lambda s: (s.sequence, s.id))
        splits = steps.filtered(lambda s: s.action == 'split')
        problems = []
        if len(splits) > 1:
            problems.append(_('Use one “Split the audience” step per workflow.'))
        if not splits:
            if steps.filtered(lambda s: s.path != 'all'):
                problems.append(_('Steps on Path A or B need a “Split the audience” step before them.'))
            return problems
        split = splits[0]
        before = steps[:list(steps).index(split)]
        if before.filtered(lambda s: s.path != 'all'):
            problems.append(_('Steps before the split are for everyone: set their path to Everyone.'))
        if split.path != 'all':
            problems.append(_('The split itself is for everyone.'))
        if split.split_by == 'words' and not (split.split_words or '').strip():
            problems.append(_('Write the words that send people to Path A.'))
        uses_leads = self.trigger == 'lead' or (self.trigger == 'form_submit' and self.form_kind == 'lead')
        if split.split_by == 'score' and not uses_leads:
            problems.append(_('Lead score only works with leads (a campaign lead or a website contact form).'))
        if split.split_by == 'ai':
            if not (split.split_question or '').strip():
                problems.append(_('Say what counts as Path A for the AI (e.g. ready to buy, asks for a demo).'))
            if not self._ai_agent():
                problems.append(_('No AI agent is available to decide the split: ask an AI manager, or split by '
                                  'words or lead score.'))
        return problems

    def _ai_agent(self):
        brand = self.brand_id.sudo()
        if 'ai_agent_id' in brand._fields and brand.ai_agent_id:
            return brand.ai_agent_id
        if 'ai.agent' not in self.env:
            return False
        user = self.requester_id or self.env.user
        options = self.env['ai.agent'].with_user(user)._chat_options()
        return self.env['ai.agent'].browse(options[0]['id']) if options else False

    def _policy(self):
        """Messages need the sending channel's own approval type (its approvers are what the dispatch checks);
        other workflows use the company's "Marketing workflow" approval type."""
        self.ensure_one()
        if any(s.action == 'message' for s in self.step_ids):
            return self._channel().sudo().approval_type_id
        Policy = self.env['approval.center.policy'].sudo().with_context(active_test=False)
        policy = Policy.search([('model_id.model', '=', 'mi.flow'), ('company_id', '=', self.company_id.id)], limit=1)
        if not policy:
            template = self.env.ref('marketing_intel_flow.policy_flow', raise_if_not_found=False)
            if not template:
                raise UserError(_('The approval type “Marketing workflow” is missing.'))
            policy = template.sudo() if template.company_id == self.company_id else \
                template.sudo().copy({'company_id': self.company_id.id, 'name': template.name})
        if not policy.active:
            raise UserError(_('Workflow approvals are switched off: activate the approval type “Marketing workflow”.'))
        return policy

    def action_request_approval(self):
        for flow in self:
            flow.check_access('write')
            if flow.state not in ('draft', 'paused'):
                raise UserError(_('This workflow is already approved or waiting for approval.'))
            problems = flow._problems()
            if problems:
                message = _('Fix this first:\n%s', '\n'.join('• ' + p for p in problems))
                if any(_('the brand’s Channels & accounts') in p for p in problems):
                    raise RedirectWarning(message, {'type': 'ir.actions.act_window', 'res_model': 'mi.brand', 'res_id': flow.brand_id.id, 'views': [(False, 'form')], 'target': 'current'},
                                          _('Open the brand'))
                raise UserError(message)
            if not flow.channel_id and any(s.action == 'message' for s in flow.step_ids):
                flow.channel_id = flow._channel()
            policy = flow._policy()
            request = self.env['approval.center.request'].sudo().create({
                'name': _('Marketing workflow: %s', flow.name), 'policy_id': policy.id,
                'company_id': flow.company_id.id, 'requester_id': self.env.uid,
                'target_model': flow._name, 'target_res_id': flow.id, 'reason': flow._approval_text(),
            })
            try:
                request.with_user(self.env.user).sudo().action_submit()
            except UserError as error:
                raise UserError(_('%(error)s Approvers are set on the approval type “%(type)s”.',
                                  error=str(error), type=policy.display_name)) from None
            flow.sudo().write({'approval_request_id': request.id, 'requester_id': self.env.uid,
                               'approved_digest': flow._digest(), 'state': 'pending'})
            flow.message_post(body=_('Sent for approval.'))
        return True

    def _approval_text(self):
        lines = [self.summary, _('Brand: %s', self.brand_id.name)]
        if self.keyword:
            lines.append(_('Keyword: %s', self.keyword))
        if self.plan_id:
            lines.append(_('Campaign: %s', self.plan_id.name))
        if self.trigger == 'form_submit':
            lines.append(_('Form: %s', dict(FORMS).get(self.form_kind)))
        paths = {'a': self.path_a_name or _('Path A'), 'b': self.path_b_name or _('Path B')}
        for step in self.step_ids.sorted('sequence'):
            text = dict(ACTIONS)[step.action]
            if step.action == 'split':
                text += ': %s (A = %s, B = %s)' % (step._split_text(), paths['a'], paths['b'])
            if step.subject:
                text += ': ' + step.subject
            if step.message:
                text += ': ' + step.message
            if step.list_id:
                text += ': ' + step.list_id.name
            if step.path != 'all':
                text = '[%s] %s' % (paths[step.path], text)
            lines.append('— ' + text)
        lines.append(_('Limits: %(once)s; at most %(cap)s message(s) per person per day; only people with a current '
                       'opt-in.', once=_('once per person') if self.once_per_person else _('every time'),
                       cap=self.daily_cap))
        return '\n'.join(lines)

    def _on_approved(self):
        """Approval Center approved the workflow: it starts with events that happen from now on."""
        for flow in self.sudo():
            if flow.state != 'pending' or flow._digest() != flow.approved_digest:
                continue
            flow.write({'state': 'active', 'approved_at': fields.Datetime.now(),
                        'last_seen_id': flow._current_max_id(), 'last_checked': fields.Datetime.now()})
            flow.message_post(body=_('Approved by %s: running from now on.', flow.approval_request_id.approver_id.name
                                     or '-'))

    def _on_refused(self):
        for flow in self.sudo().filtered(lambda f: f.state == 'pending'):
            flow.write({'state': 'draft', 'approved_digest': False})
            flow.message_post(body=_('The approval was refused. Change the workflow and ask again.'))

    def action_pause(self):
        self.filtered(lambda f: f.state == 'active').write({'state': 'paused'})
        return True

    def action_resume(self):
        for flow in self.filtered(lambda f: f.state == 'paused'):
            if flow._digest() != flow.approved_digest or flow.approval_request_id.state != 'approved':
                raise UserError(_('The workflow changed since it was approved: ask for approval again.'))
            flow.write({'state': 'active', 'last_seen_id': flow._current_max_id(),
                        'last_checked': fields.Datetime.now()})
        return True

    def action_open_runs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow.run', 'name': _('Runs: %s', self.name),
                'view_mode': 'list,form', 'domain': [('flow_id', '=', self.id)]}

    # ------------------------------------------------------------------ engine

    def _source_model(self):
        if self.trigger == 'form_submit':
            return 'mailing.contact' if self.form_kind == 'newsletter' else 'crm.lead'
        return {'social_comment': 'omni.social.activity', 'social_message': 'omni.social.activity',
                'event_registration': 'event.registration', 'lead': 'crm.lead'}.get(self.trigger)

    def _current_max_id(self):
        model = self._source_model()
        if not model or model not in self.env:
            return 0
        self.env.cr.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{self.env[model]._table}"')
        return self.env.cr.fetchone()[0]

    @api.model
    def _cron_run(self):
        for flow in self.sudo().search([('state', '=', 'active')]):
            try:
                with self.env.cr.savepoint():
                    flow._run_once()
            except Exception as error:  # noqa: BLE001 - one broken workflow must not stop the others
                _logger.exception('Marketing workflow %s failed', flow.id)
                flow.message_post(body=_('This check failed and will be retried: %s', str(error)[:300]))

    def _run_once(self):
        self.ensure_one()
        if self._digest() != self.approved_digest or self.approval_request_id.state != 'approved':
            self.write({'state': 'paused'})
            self.message_post(body=_('Paused: it no longer matches what was approved.'))
            return
        now = fields.Datetime.now()
        events = self._collect()
        for event in events:
            self._handle(event)
        values = {'last_checked': now}
        ids = [e['id'] for e in events if e.get('id')]
        if ids:
            values['last_seen_id'] = max(ids + [self.last_seen_id])
        self.write(values)

    def _collect(self):
        """New events since the last check, as plain dicts."""
        self.ensure_one()
        keyword = _handle(self.keyword)
        events = []
        if self.trigger in ('social_comment', 'social_message'):
            domain = [('id', '>', self.last_seen_id), ('connection_id', 'in', self._connections().ids),
                      ('kind', '=', 'comment' if self.trigger == 'social_comment' else 'message')]
            if self.trigger == 'social_comment' and self.plan_id:
                domain.append(('root_key', 'in', self._plan_post_keys() or ['-']))
            for activity in self.env['omni.social.activity'].sudo().search(domain, order='id', limit=BATCH):
                text = activity.body or ''
                author = _handle(activity.author)
                if author and author == _handle(activity.connection_id.profile_name):
                    continue  # our own replies
                if keyword and keyword not in text.casefold():
                    events.append({'id': activity.id, 'ignore': True})
                    continue
                provider = activity.connection_id.provider
                events.append({'id': activity.id, 'key': f'{provider}:{author}', 'label': activity.author or '?',
                               'partner': self._partner_from_handle(provider, author), 'text': text,
                               'ref': f'omni.social.activity,{activity.id}'})
        elif self.trigger == 'event_registration' and 'event.registration' in self.env:
            events_ids = [i.res_id for i in self.plan_id.item_ids if i.res_model == 'event.event' and i.res_id]
            for reg in self.env['event.registration'].sudo().search(
                    [('id', '>', self.last_seen_id), ('event_id', 'in', events_ids)], order='id', limit=BATCH):
                events.append({'id': reg.id, 'key': f'partner:{reg.partner_id.id}' if reg.partner_id else
                               f'email:{(reg.email or "").casefold()}', 'label': reg.name or reg.email or '?',
                               'partner': reg.partner_id, 'text': reg.event_id.name, 'email': reg.email,
                               'phone': reg.phone,
                               'ref': f'event.registration,{reg.id}'})
        elif self.trigger == 'lead' and 'crm.lead' in self.env and self.plan_id.utm_campaign_id:
            for lead in self.env['crm.lead'].sudo().search(
                    [('id', '>', self.last_seen_id), ('campaign_id', '=', self.plan_id.utm_campaign_id.id)],
                    order='id', limit=BATCH):
                events.append(self._lead_event(lead))
        elif self.trigger == 'form_submit' and self.form_kind == 'lead' and 'crm.lead' in self.env:
            website = self.env.ref('utm.utm_medium_website', raise_if_not_found=False)
            domain = [('id', '>', self.last_seen_id), ('company_id', 'in', [False, self.company_id.id]),
                      ('medium_id', '=', website.id if website else -1)]
            if self.plan_id.utm_campaign_id:
                domain.append(('campaign_id', '=', self.plan_id.utm_campaign_id.id))
            for lead in self.env['crm.lead'].sudo().search(domain, order='id', limit=BATCH):
                events.append(self._lead_event(lead))
        elif self.trigger == 'form_submit' and self.form_kind == 'newsletter' and 'mailing.contact' in self.env:
            domain = [('id', '>', self.last_seen_id)]
            if self.mailing_list_id:
                domain.append(('list_ids', 'in', self.mailing_list_id.ids))
            for contact in self.env['mailing.contact'].sudo().search(domain, order='id', limit=BATCH):
                email = (contact.email or '').casefold()
                events.append({'id': contact.id, 'key': f'email:{email}', 'label': contact.name or contact.email or '?',
                               'partner': self.env['res.partner'], 'email': contact.email, 'text': contact.name or '',
                               'ref': f'mailing.contact,{contact.id}'})
        elif self.trigger == 'email_click' and 'mailing.trace' in self.env:
            mailings = [i.res_id for i in self.plan_id.item_ids if i.res_model == 'mailing.mailing' and i.res_id]
            Partner = self.env['res.partner'].sudo()
            for trace in self.env['mailing.trace'].sudo().search(
                    [('mass_mailing_id', 'in', mailings), ('links_click_datetime', '>', self.last_checked)],
                    order='links_click_datetime', limit=BATCH):
                email = (trace.email or '').casefold()
                partner = Partner.search([('email', '=ilike', email), ('company_id', 'in',
                                                                       [False, self.company_id.id])], limit=1)
                events.append({'key': f'email:{email}', 'label': trace.email or '?', 'partner': partner,
                               'email': trace.email, 'text': trace.mass_mailing_id.subject or '',
                               'ref': f'mailing.trace,{trace.id}'})
        return events

    def _lead_event(self, lead):
        from odoo.addons.marketing_intel_plan.models.plan import html2plaintext
        text = '\n'.join(filter(None, [lead.name, html2plaintext(lead.description or '')]))
        return {'id': lead.id, 'key': f'partner:{lead.partner_id.id}' if lead.partner_id else
                f'email:{(lead.email_from or "").casefold()}', 'label': lead.partner_name or lead.contact_name or
                lead.email_from or lead.name, 'partner': lead.partner_id, 'email': lead.email_from,
                'phone': lead.phone, 'score': lead.probability, 'text': text[:2000], 'ref': f'crm.lead,{lead.id}'}

    def _plan_post_keys(self):
        keys = []
        for item in self.plan_id.item_ids.filtered(lambda i: i.res_model == 'omni.social.campaign' and i.res_id):
            campaign = self.env['omni.social.campaign'].sudo().browse(item.res_id).exists()
            keys += [k for k in campaign.publication_ids.mapped('result_key') if k]
        return keys

    def _partner_from_handle(self, provider, handle):
        if not handle or 'omni.partner.channel' not in self.env:
            return self.env['res.partner']
        links = self.env['omni.partner.channel'].sudo().search([('channel_type_id.code', '=', provider),
                                                                 ('partner_id.company_id', 'in',
                                                                  [False, self.company_id.id])])
        match = links.filtered(lambda link: _handle(link.handle).rstrip('/').split('/')[-1] == handle)
        return match[:1].partner_id

    def _handle(self, event):
        """One person, one run: every step done or skipped with a reason."""
        if event.get('ignore'):
            return
        Run = self.env['mi.flow.run'].sudo()
        if self.once_per_person and Run.search_count([('flow_id', '=', self.id), ('person_key', '=', event['key'])]):
            return
        partner = event.get('partner') or self.env['res.partner']
        contact = self.env['mm.contact'].sudo().search([('partner_id', '=', partner.id),
                                                         ('company_id', '=', self.company_id.id)], limit=1) \
            if partner else self.env['mm.contact']
        run = Run.create({'flow_id': self.id, 'person_key': event['key'], 'person': event['label'],
                          'partner_id': partner.id, 'mm_contact_id': contact.id, 'source_ref': event.get('ref'),
                          'trigger_text': (event.get('text') or '')[:2000],
                          'email': event.get('email') or partner.email or False,
                          'phone': event.get('phone') or partner.phone or False, 'score': event.get('score') or 0})
        self._run_steps(run)

    def _run_steps(self, run, start=0):
        """Run the steps from position ``start``; after a split only the chosen path. An AI split pauses the run
        until the AI answers (``_ai_agent_finished``)."""
        steps = self.step_ids.sorted(lambda s: (s.sequence, s.id))
        log = [run.log] if run.log else []
        done = run.done_count
        paths = {'a': self.path_a_name or _('Path A'), 'b': self.path_b_name or _('Path B')}
        for index, step in enumerate(steps):
            if index < start:
                continue
            if step.path != 'all' and step.path != run.path:
                continue
            if step.action == 'split':
                path, reason = step._split(run)
                if path is None:  # the AI decides later
                    run.write({'state': 'waiting', 'log': '\n'.join(log + ['… %s' % reason]), 'step_pos': index + 1,
                               'done_count': done})
                    return
                run.path = path
                log.append('↳ %s: %s (%s)' % (dict(ACTIONS)['split'], paths[path], reason))
                continue
            try:
                with self.env.cr.savepoint():
                    ok, note = step._execute(run, run.mm_contact_id, run.partner_id, {'text': run.trigger_text})
            except (AccessError, UserError, ValidationError) as error:
                ok, note = False, _('Error: %s', str(error).splitlines()[0][:200])
                run.state = 'failed'
            done += ok
            label = dict(ACTIONS)[step.action]
            if step.path != 'all':
                label = '[%s] %s' % (paths[step.path], label)
            log.append('%s %s — %s' % ('✓' if ok else '–', label, note))
        values = {'log': '\n'.join(log), 'done_count': done, 'step_pos': len(steps)}
        if run.state != 'failed':
            values['state'] = 'done' if done else 'skipped'
        run.write(values)

    def _ai_agent_finished(self, ai_run):
        """The AI answered a split: continue that person's run on the chosen path (B if the answer is unusable)."""
        run = self.env['mi.flow.run'].sudo().search([('ai_run_id', '=', ai_run.id), ('state', '=', 'waiting')],
                                                    limit=1)
        if not run:
            return
        path, reason = 'b', _('The AI gave no usable answer: Path B.')
        if ai_run.state == 'completed':
            try:
                from odoo.addons.marketing_intel_ai.models.schema import extract_json
                data = extract_json(ai_run.answer)
                if data.get('path') in ('a', 'b'):
                    path, reason = data['path'], str(data.get('reason') or '')[:200] or _('AI decision')
            except Exception:  # noqa: BLE001 - any unusable answer falls back to Path B, logged
                pass
        flow = run.flow_id.sudo()
        if flow._digest() != flow.approved_digest or flow.state != 'active':
            run.write({'state': 'skipped', 'log': (run.log or '') + '\n' + _('Stopped: the workflow changed or was '
                                                                             'paused while the AI was deciding.')})
            return
        run.write({'path': path, 'state': 'running', 'log': (run.log or '') + '\n↳ %s: %s (%s)' % (
            dict(ACTIONS)['split'], (flow.path_a_name if path == 'a' else flow.path_b_name) or path.upper(), reason)})
        flow._run_steps(run, start=run.step_pos)

    def _queue_message(self, run, contact, body):
        """Queue one Omnichannel message with this workflow's approval as its evidence."""
        from odoo.addons.omni_channel.models.command import digest, internal as omni_internal
        channel = self._channel().sudo()
        code = channel.channel_type_id.code
        address = contact._address(code)
        sender = channel.selected_sender_id
        if not sender or sender.health != 'healthy':
            raise UserError(_('The channel has no verified sender.'))
        request = self.approval_request_id.sudo()
        values = {'name': self.name, 'channel_id': channel.id, 'recipient': address, 'body': body,
                  'reason': _('Marketing workflow “%s”', self.name), 'requester_id': self.requester_id.id,
                  'mi_flow_run_id': run.id}
        Command = omni_internal(self.env['omni.command'].sudo())
        if code == 'telegram' and 'conversation_id' in Command._fields:
            values['conversation_id'] = contact.telegram_conversation_id.id
        command = Command.create(values).with_user(self.requester_id).sudo()
        payload = {
            'schema': 1, 'uuid': command.uuid, 'company': command.company_id.id,
            'purpose': command.purpose_id.code, 'channel': channel.id, 'generation': channel.generation,
            'sender': sender.external_key, 'account': sender.account_id.external_account_key,
            'recipient': address, 'body': body, 'operation': 'message.send', **command._extra_payload(),
        }
        omni_internal(command).write({
            'state': 'queued', 'sender_id': sender.id, 'channel_generation': channel.generation,
            'payload': payload, 'payload_hash': digest(payload), 'policy_hash': digest(command._policy_document()),
            'expires_at': fields.Datetime.now() + timedelta(hours=24), 'approval_request_id': request.id,
        })
        command._audit('message.queued', _('Queued by the approved marketing workflow “%s”.', self.name))
        return command

    def _messages_today(self, contact, person_key=None):
        """Workflow messages to this person today, across all workflows: WhatsApp/Telegram, email and SMS."""
        start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        count = self.env['omni.command'].sudo().search_count([('mi_flow_run_id.mm_contact_id', '=', contact.id),
                                                              ('create_date', '>=', start),
                                                              ('state', '!=', 'cancelled')]) if contact else 0
        if person_key:
            runs = self.env['mi.flow.run'].sudo().search([('person_key', '=', person_key), ('create_date', '>=', start),
                                                          ('company_id', '=', self.company_id.id)])
            count += sum(runs.mapped('direct_sent'))
        return count

    def _email_from(self):
        brand = self.brand_id.sudo()
        return ('email_from' in brand._fields and brand.email_from) or self.company_id.email_formatted or \
            self.env.user.email_formatted


class FlowStep(models.Model):
    _name = 'mi.flow.step'
    _description = 'Marketing workflow step'
    _order = 'flow_id, sequence, id'

    flow_id = fields.Many2one('mi.flow', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='flow_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    action = fields.Selection(ACTIONS, required=True, default='message', string='Do')
    message = fields.Text(help='Plain text. {first_name} and {name} are filled for each person.')
    list_id = fields.Many2one('mm.list', string='List')
    note = fields.Char(string='To-do / lead note')
    path = fields.Selection(PATHS, default='all', required=True, string='Path',
                            help='After a split: which path does this step. Everyone: all people.')
    subject = fields.Char(help='Email subject. {first_name} and {name} are filled for each person.')
    split_by = fields.Selection(SPLITS, default='ai', string='Split by')
    split_question = fields.Char(string='Path A means', help='For the AI: who goes to Path A, e.g. "ready to buy, '
                                 'asks for a price, a demo or a meeting".')
    split_words = fields.Char(string='Path A words', help='Comma-separated: if what they wrote contains one, Path A.')
    split_score = fields.Integer(default=50, string='Path A from score',
                                 help='Leads with this probability (%) or more go to Path A.')

    details = fields.Char(compute='_compute_details', string='Details')

    @api.depends('action', 'message', 'subject', 'note', 'split_by', 'split_question', 'split_words', 'split_score')
    def _compute_details(self):
        for step in self:
            if step.action == 'split':
                step.details = step._split_text()
            elif step.action == 'email':
                step.details = '%s — %s' % (step.subject or '', (step.message or '').replace('\n', ' ')[:80])
            elif step.action in ('message', 'sms'):
                step.details = (step.message or '').replace('\n', ' ')[:100]
            elif step.action == 'add_list' and 'list_id' in step._fields:
                step.details = step.list_id.name or ''
            else:
                step.details = step.note or ''

    @api.model_create_multi
    def create(self, vals_list):
        steps = super().create(vals_list)
        steps.flow_id._changed_after_approval()
        return steps

    def _split_text(self):
        self.ensure_one()
        if self.split_by == 'words':
            return _('Path A if they wrote: %s', self.split_words or '-')
        if self.split_by == 'score':
            return _('Path A if the lead score is %s%% or more', self.split_score)
        return _('the AI decides; Path A means: %s', self.split_question or '-')

    def _split(self, run):
        """(path, reason); (None, note) when the AI will decide later."""
        self.ensure_one()
        if self.split_by == 'words':
            words = [w.strip().casefold() for w in (self.split_words or '').split(',') if w.strip()]
            text = (run.trigger_text or '').casefold()
            hit = next((w for w in words if w in text), None)
            return ('a', _('wrote “%s”', hit)) if hit else ('b', _('none of the words'))
        if self.split_by == 'score':
            return ('a' if run.score >= self.split_score else 'b'), _('score %s%%', round(run.score))
        flow = self.flow_id.sudo()
        agent = flow._ai_agent()
        if not agent or not (run.trigger_text or '').strip():
            return 'b', _('no AI agent or nothing written: Path B')
        prompt = AI_SPLIT_PROMPT % {'a': flow.path_a_name or 'A', 'b': flow.path_b_name or 'B',
                                    'rule': self.split_question or '', 'text': run.trigger_text[:3000]}
        try:
            with self.env.cr.savepoint():
                ai_run = self.env['ai.agent.run'].with_user(flow.requester_id or flow.user_id)._queue(
                    agent.with_user(flow.requester_id or flow.user_id), prompt,
                    origin=flow.with_user(flow.requester_id or flow.user_id))
        except (AccessError, UserError) as error:
            return 'b', _('the AI could not be asked (%s): Path B', str(error).splitlines()[0][:120])
        run.ai_run_id = ai_run.id
        return None, _('waiting for the AI to decide the path')

    def write(self, vals):
        result = super().write(vals)
        self.flow_id._changed_after_approval()
        self.flow_id._sync_owner_activity()
        return result

    def unlink(self):
        flows = self.flow_id
        result = super().unlink()
        flows._changed_after_approval()
        return result

    def _execute(self, run, contact, partner, event):
        """(done, note) for one person."""
        flow = self.flow_id
        if self.action == 'message':
            if not contact:
                return False, _('Not a known contact with an opt-in: skipped.')
            channel = flow._channel().sudo()
            code = channel.channel_type_id.code
            address = contact._address(code)
            refusal = contact._send_refusal(code, address) if address else _('No %s address.', code)
            if refusal:
                return False, refusal
            if 'mi.consent.subject' in self.env:
                subject = self.env['mi.consent.subject']._find_or_create(
                    phone=address, partner=contact.partner_id, name=contact.name, company=flow.company_id)
                if not subject._allows(code):
                    return False, _('Opted out of %s in the consent ledger.', code)
            if flow._messages_today(contact, run.person_key) >= max(flow.daily_cap, 0):
                return False, _('Daily limit reached for this person.')
            from odoo.addons.messaging_marketing.models.mailing import render
            command = flow._queue_message(run, contact, render(self.message, contact))
            return True, _('Queued to %s', command.recipient)
        if self.action == 'email':
            return self._send_email(run, partner)
        if self.action == 'sms':
            return self._send_sms(run, partner)
        if self.action == 'add_list':
            if not contact:
                return False, _('Not a known Messaging contact: skipped.')
            Sub = self.env['mm.subscription'].sudo()
            if Sub.search_count([('contact_id', '=', contact.id), ('list_id', '=', self.list_id.id)]):
                return False, _('Already in %s.', self.list_id.name)
            Sub.create({'contact_id': contact.id, 'list_id': self.list_id.id})
            return True, _('Added to %s.', self.list_id.name)
        if self.action == 'lead':
            lead = self.env['crm.lead'].sudo().create({
                'name': '%s: %s' % (flow.name, run.person), 'partner_id': partner.id or False,
                'contact_name': False if partner else run.person, 'user_id': flow.user_id.id,
                'company_id': flow.company_id.id, 'description': '%s\n%s' % (self.note or '', run.trigger_text),
                'campaign_id': flow.plan_id.utm_campaign_id.id or False,
            })
            return True, _('Lead created: %s', lead.name)
        if self.action == 'todo':
            flow.activity_schedule('mail.mail_activity_data_todo', user_id=flow.user_id.id,
                                   summary=('%s: %s' % (run.person, self.note or flow.name))[:250],
                                   note=run.trigger_text)
            return True, _('To-do for %s.', flow.user_id.name)
        return False, _('Unknown step.')

    def _fill(self, text, run, partner):
        name = partner.name or run.person or ''
        return (text or '').replace('{first_name}', name.split(' ')[0] if name else '').replace('{name}', name)

    def _consent_allows(self, channel, run, partner, email=None, phone=None):
        if 'mi.consent.subject' not in self.env:
            return True
        subject = self.env['mi.consent.subject']._find_or_create(email=email, phone=phone, partner=partner or None,
                                                                 name=run.person, company=self.flow_id.company_id)
        return subject._allows(channel)

    def _send_email(self, run, partner):
        from odoo import tools
        from odoo.addons.marketing_intel_plan.models.plan import text_to_html
        flow = self.flow_id
        email = tools.email_normalize(run.email or partner.email or '')
        if not email:
            return False, _('No email address: skipped.')
        if self.env['mail.blacklist'].sudo().search_count([('email', '=', email), ('active', '=', True)]):
            return False, _('%s unsubscribed from emails: skipped.', email)
        if not self._consent_allows('email', run, partner, email=email):
            return False, _('Opted out of email in the consent ledger.')
        if flow._messages_today(run.mm_contact_id, run.person_key) >= max(flow.daily_cap, 0):
            return False, _('Daily limit reached for this person.')
        self.env['mail.mail'].sudo().create({
            'subject': self._fill(self.subject, run, partner), 'email_to': email, 'email_from': flow._email_from(),
            'body_html': text_to_html(self._fill(self.message, run, partner)), 'auto_delete': False,
            'recipient_ids': [(6, 0, partner.ids)] if partner else False,
        })
        run.direct_sent += 1
        return True, _('Email queued to %s', email)

    def _send_sms(self, run, partner):
        flow = self.flow_id
        number = run.phone or partner.phone or ''
        number = (partner._phone_format(number=number) if partner else
                  self.env['res.partner'].new({'country_id': flow.company_id.country_id.id})._phone_format(
                      number=number)) or number
        if not number:
            return False, _('No phone number: skipped.')
        if self.env['phone.blacklist'].sudo().search_count([('number', '=', number), ('active', '=', True)]):
            return False, _('%s unsubscribed from SMS: skipped.', number)
        if not self._consent_allows('sms', run, partner, phone=number):
            return False, _('Opted out of SMS in the consent ledger.')
        if flow._messages_today(run.mm_contact_id, run.person_key) >= max(flow.daily_cap, 0):
            return False, _('Daily limit reached for this person.')
        self.env['sms.sms'].sudo().create({'number': number, 'body': self._fill(self.message, run, partner),
                                           'partner_id': partner.id or False})
        run.direct_sent += 1
        return True, _('SMS queued to %s', number)


class FlowRun(models.Model):
    _name = 'mi.flow.run'
    _description = 'Marketing workflow run'
    _order = 'create_date desc, id desc'

    flow_id = fields.Many2one('mi.flow', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='flow_id.company_id', store=True)
    brand_id = fields.Many2one(related='flow_id.brand_id', store=True)
    person = fields.Char(readonly=True, string='Who')
    person_key = fields.Char(readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', readonly=True, string='Contact')
    mm_contact_id = fields.Many2one('mm.contact', readonly=True, string='Messaging contact')
    source_ref = fields.Reference(selection='_selection_source', readonly=True, string='Because of')
    trigger_text = fields.Text(readonly=True, string='What they wrote')
    email = fields.Char(readonly=True)
    phone = fields.Char(readonly=True)
    score = fields.Float(readonly=True, string='Lead score')
    path = fields.Selection([('a', 'Path A'), ('b', 'Path B')], readonly=True)
    step_pos = fields.Integer(readonly=True)
    done_count = fields.Integer(readonly=True)
    direct_sent = fields.Integer(readonly=True, string='Emails and SMS sent')
    ai_run_id = fields.Many2one('ai.agent.run', readonly=True, string='AI decision', index='btree_not_null')
    state = fields.Selection([('running', 'Running'), ('waiting', 'Waiting for the AI'), ('done', 'Done'),
                              ('skipped', 'Skipped'), ('failed', 'Error')], default='running', readonly=True,
                             string='Result')
    log = fields.Text(readonly=True, string='Steps')
    command_ids = fields.One2many('omni.command', 'mi_flow_run_id', readonly=True, string='Messages')
    message_count = fields.Integer(compute='_compute_message_count', string='Messages')

    @api.model
    def _selection_source(self):
        models_ = [('omni.social.activity', 'Social activity'), ('event.registration', 'Event registration'),
                   ('crm.lead', 'Lead'), ('mailing.trace', 'Email'), ('mailing.contact', 'Newsletter sign-up')]
        return [(m, label) for m, label in models_ if m in self.env]

    @api.depends('command_ids')
    def _compute_message_count(self):
        for run in self:
            run.message_count = len(run.command_ids) + run.direct_sent


class FlowRecipe(models.Model):
    """A ready-made workflow to start from. Shipped ones and ones a manager saved from a working workflow."""
    _name = 'mi.flow.recipe'
    _description = 'Marketing workflow recipe'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True, help='What it is for, shown on the recipe card.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Char(default='flash_on', help='Icon name on the card, e.g. forum, mail, event_available, mouse.')
    trigger = fields.Selection(TRIGGERS, required=True, string='When')
    keyword = fields.Char(help='Only when the comment or message contains this word.')
    form_kind = fields.Selection(FORMS, default='lead', string='Form')
    path_a_name = fields.Char(string='Path A is', translate=True)
    path_b_name = fields.Char(string='Path B is', translate=True)
    step_ids = fields.One2many('mi.flow.recipe.step', 'recipe_id', string='Then', copy=True)
    summary = fields.Char(compute='_compute_summary', string='What it does')
    source_flow_id = fields.Many2one('mi.flow', string='Saved from', readonly=True, copy=False, ondelete='set null')
    use_count = fields.Integer(compute='_compute_use_count', string='Workflows made from it')

    @api.depends('trigger', 'keyword', 'step_ids.action')
    def _compute_summary(self):
        triggers, actions = dict(TRIGGERS), dict(ACTIONS)
        for recipe in self:
            when = triggers.get(recipe.trigger, '')
            when = when[:1].lower() + when[1:]
            if recipe.keyword:
                when += _(' with “%s”', recipe.keyword)
            steps = ', '.join(actions[s.action][:1].lower() + actions[s.action][1:]
                              for s in recipe.step_ids.sorted('sequence')) or '…'
            recipe.summary = _('When %(when)s → %(steps)s', when=when, steps=steps)

    def _compute_use_count(self):
        counts = dict(self.env['mi.flow']._read_group([('recipe_id', 'in', self.ids)], ['recipe_id'], ['__count']))
        for recipe in self:
            recipe.use_count = counts.get(recipe, 0)

    def action_blank(self):
        """Start a workflow from scratch (the empty form)."""
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow', 'view_mode': 'form', 'views': [(False, 'form')],
                'target': 'current', 'name': _('New workflow'),
                'context': {k: v for k, v in self.env.context.items() if k == 'default_brand_id'}}

    def action_use(self):
        """A draft workflow from this recipe, for the brand in view; asks which brand when that is not clear."""
        self.ensure_one()
        brand = self.env['mi.brand'].browse(self.env.context.get('default_brand_id')).exists()
        if not brand:
            brands = self.env['mi.brand'].search([], limit=2)
            if not brands:
                raise UserError(_('Create a brand first.'))
            if len(brands) > 1:
                return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow.recipe.use', 'view_mode': 'form',
                        'target': 'new', 'name': _('Use “%s”', self.name),
                        'context': {'default_recipe_id': self.id}}
            brand = brands
        return self._make_flow(brand)

    def _make_flow(self, brand):
        self.ensure_one()
        values = {'name': self.name, 'brand_id': brand.id, 'trigger': self.trigger, 'keyword': self.keyword,
                  'recipe_id': self.id, 'form_kind': self.form_kind,
                  'step_ids': [(0, 0, step._step_values()) for step in self.step_ids.sorted('sequence')]}
        for name in ('path_a_name', 'path_b_name'):
            if self[name]:
                values[name] = self[name]
        flow = self.env['mi.flow'].create(values)
        flow.message_post(body=_('Started from the recipe “%s”.', self.name))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow', 'res_id': flow.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current'}


class FlowRecipeStep(models.Model):
    _name = 'mi.flow.recipe.step'
    _description = 'Marketing workflow recipe step'
    _order = 'recipe_id, sequence, id'

    recipe_id = fields.Many2one('mi.flow.recipe', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    action = fields.Selection(ACTIONS, required=True, default='message', string='Do')
    message = fields.Text(help='Plain text. {first_name} and {name} are filled for each person.', translate=True)
    note = fields.Char(string='To-do / lead note', translate=True)
    path = fields.Selection(PATHS, default='all', required=True, string='Path')
    subject = fields.Char(translate=True)
    split_by = fields.Selection(SPLITS, default='ai', string='Split by')
    split_question = fields.Char(string='Path A means', translate=True)
    split_words = fields.Char(string='Path A words', translate=True)
    split_score = fields.Integer(default=50, string='Path A from score')

    details = fields.Char(compute='_compute_details', string='Details')

    @api.depends('action', 'message', 'subject', 'note', 'split_by', 'split_question', 'split_words', 'split_score')
    def _compute_details(self):
        for step in self:
            if step.action == 'split':
                step.details = step._split_text()
            elif step.action == 'email':
                step.details = '%s — %s' % (step.subject or '', (step.message or '').replace('\n', ' ')[:80])
            elif step.action in ('message', 'sms'):
                step.details = (step.message or '').replace('\n', ' ')[:100]
            elif step.action == 'add_list' and 'list_id' in step._fields:
                step.details = step.list_id.name or ''
            else:
                step.details = step.note or ''

    def _split_text(self):
        return self.env['mi.flow.step'].new({'split_by': self.split_by, 'split_words': self.split_words,
                                             'split_score': self.split_score,
                                             'split_question': self.split_question})._split_text()

    def _step_values(self):
        return {name: self[name] for name in STEP_COPY}


class FlowRecipeUse(models.TransientModel):
    _name = 'mi.flow.recipe.use'
    _description = 'Use a workflow recipe'

    recipe_id = fields.Many2one('mi.flow.recipe', required=True, readonly=True)
    brand_id = fields.Many2one('mi.brand', required=True, string='For brand')

    def action_create(self):
        self.ensure_one()
        return self.recipe_id._make_flow(self.brand_id)


class FlowFromRecipe(models.Model):
    _inherit = 'mi.flow'

    recipe_id = fields.Many2one('mi.flow.recipe', string='From recipe', readonly=True, copy=False, index=True,
                                ondelete='set null')

    def action_save_recipe(self):
        """Managers: keep this workflow as a recipe (saving again updates it). Brand-specific settings — social
        pages, sending channel, lists, campaign, limits — are not kept: whoever uses the recipe sets them."""
        self.ensure_one()
        if not self.env.user.has_group('marketing_intel.group_mi_manager'):
            raise AccessError(_('Only a marketing manager saves workflows as recipes.'))
        Recipe = self.env['mi.flow.recipe'].with_context(active_test=False)
        values = {'trigger': self.trigger, 'keyword': self.keyword, 'form_kind': self.form_kind,
                  'path_a_name': self.path_a_name if self.has_split else False,
                  'path_b_name': self.path_b_name if self.has_split else False,
                  'step_ids': [(5, 0, 0)] + [(0, 0, {name: step[name] for name in STEP_COPY})
                                             for step in self.step_ids.sorted('sequence')]}
        recipe = Recipe.search([('source_flow_id', '=', self.id)], limit=1)
        if recipe:
            recipe.write(dict(values, active=True))
        else:
            if Recipe.search_count([('name', '=ilike', self.name)]):
                raise UserError(_('A recipe called “%s” already exists. Rename this workflow before saving it as a '
                                  'recipe, or edit that recipe (Workflows › Recipes).', self.name))
            recipe = Recipe.create(dict(values, name=self.name, description=self.summary, source_flow_id=self.id,
                                        icon=dict(RECIPE_ICONS).get(self.trigger, 'flash_on'),
                                        sequence=100))
        self.message_post(body=_('Saved as the recipe “%s”.', recipe.name))
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow.recipe', 'res_id': recipe.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
