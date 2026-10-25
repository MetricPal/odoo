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
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

TRIGGERS = [
    ('social_comment', 'Someone comments on a post'),
    ('social_message', 'Someone sends us a private message'),
    ('event_registration', 'Someone registers for an event'),
    ('email_click', 'Someone clicks a link in an email'),
    ('lead', 'A new lead comes from a campaign'),
]
ACTIONS = [
    ('message', 'Send a WhatsApp / Telegram message'),
    ('add_list', 'Add them to a Messaging list'),
    ('lead', 'Create a lead'),
    ('todo', 'Create a to-do for the owner'),
]
FROZEN = {'trigger', 'keyword', 'plan_id', 'connection_ids', 'channel_id', 'daily_cap', 'once_per_person',
          'brand_id'}
BATCH = 200


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _handle(value):
    return (value or '').strip().lstrip('@').casefold()


class Flow(models.Model):
    _name = 'mi.flow'
    _description = 'Marketing workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
                      for s in self.step_ids.sorted(lambda s: (s.sequence, s.id))],
        }

    def _digest(self):
        return _digest(self._payload())

    def write(self, vals):
        result = super().write(vals)
        if FROZEN & vals.keys():
            self._changed_after_approval()
        return result

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
            problems.append(_('Choose the social pages to watch (or set them in Brand › Settings › Channels & '
                              'accounts).'))
        if self.trigger in ('event_registration', 'email_click', 'lead') and not self.plan_id:
            problems.append(_('Choose the campaign whose event, emails or leads it watches.'))
        if self.trigger == 'lead' and 'crm.lead' not in self.env:
            problems.append(_('Install CRM to watch leads.'))
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
            if step.action == 'add_list' and not step.list_id:
                problems.append(_('Choose the list to add people to.'))
            if step.action == 'lead' and 'crm.lead' not in self.env:
                problems.append(_('Install CRM to create leads.'))
        return list(dict.fromkeys(problems))

    def _policy(self):
        """Messages need the sending channel's own approval type (its approvers are what the dispatch checks);
        other workflows use the company's "Marketing campaign" approval type."""
        self.ensure_one()
        if any(s.action == 'message' for s in self.step_ids):
            return self._channel().sudo().approval_type_id
        return self.env['mi.plan'].new({'brand_id': self.brand_id.id})._campaign_policy()

    def action_request_approval(self):
        for flow in self:
            flow.check_access('write')
            if flow.state not in ('draft', 'paused'):
                raise UserError(_('This workflow is already approved or waiting for approval.'))
            problems = flow._problems()
            if problems:
                raise UserError(_('Fix this first:\n%s', '\n'.join('• ' + p for p in problems)))
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
        for step in self.step_ids.sorted('sequence'):
            text = dict(ACTIONS)[step.action]
            if step.message:
                text += ': ' + step.message
            if step.list_id:
                text += ': ' + step.list_id.name
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
                               'partner': reg.partner_id, 'text': reg.event_id.name,
                               'ref': f'event.registration,{reg.id}'})
        elif self.trigger == 'lead' and 'crm.lead' in self.env and self.plan_id.utm_campaign_id:
            for lead in self.env['crm.lead'].sudo().search(
                    [('id', '>', self.last_seen_id), ('campaign_id', '=', self.plan_id.utm_campaign_id.id)],
                    order='id', limit=BATCH):
                events.append({'id': lead.id, 'key': f'partner:{lead.partner_id.id}' if lead.partner_id else
                               f'email:{(lead.email_from or "").casefold()}', 'label': lead.partner_name or
                               lead.contact_name or lead.email_from or lead.name, 'partner': lead.partner_id,
                               'text': lead.name, 'ref': f'crm.lead,{lead.id}'})
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
                               'text': trace.mass_mailing_id.subject or '', 'ref': f'mailing.trace,{trace.id}'})
        return events

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
                          'trigger_text': (event.get('text') or '')[:500]})
        log, done = [], 0
        for step in self.step_ids.sorted(lambda s: (s.sequence, s.id)):
            try:
                with self.env.cr.savepoint():
                    ok, note = step._execute(run, contact, partner, event)
            except (AccessError, UserError, ValidationError) as error:
                ok, note = False, _('Error: %s', str(error).splitlines()[0][:200])
                run.state = 'failed'
            done += ok
            log.append('%s %s — %s' % ('✓' if ok else '–', dict(ACTIONS)[step.action], note))
        values = {'log': '\n'.join(log)}
        if run.state != 'failed':
            values['state'] = 'done' if done else 'skipped'
        run.write(values)

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

    def _messages_today(self, contact):
        start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        return self.env['omni.command'].sudo().search_count([('mi_flow_run_id.mm_contact_id', '=', contact.id),
                                                             ('create_date', '>=', start),
                                                             ('state', '!=', 'cancelled')])


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

    @api.model_create_multi
    def create(self, vals_list):
        steps = super().create(vals_list)
        steps.flow_id._changed_after_approval()
        return steps

    def write(self, vals):
        result = super().write(vals)
        self.flow_id._changed_after_approval()
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
            if flow._messages_today(contact) >= max(flow.daily_cap, 0):
                return False, _('Daily limit reached for this person.')
            from odoo.addons.messaging_marketing.models.mailing import render
            command = flow._queue_message(run, contact, render(self.message, contact))
            return True, _('Queued to %s', command.recipient)
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
    state = fields.Selection([('running', 'Running'), ('done', 'Done'), ('skipped', 'Skipped'),
                              ('failed', 'Error')], default='running', readonly=True, string='Result')
    log = fields.Text(readonly=True, string='Steps')
    command_ids = fields.One2many('omni.command', 'mi_flow_run_id', readonly=True, string='Messages')
    message_count = fields.Integer(compute='_compute_message_count', string='Messages')

    @api.model
    def _selection_source(self):
        models_ = [('omni.social.activity', 'Social activity'), ('event.registration', 'Event registration'),
                   ('crm.lead', 'Lead'), ('mailing.trace', 'Email')]
        return [(m, label) for m, label in models_ if m in self.env]

    @api.depends('command_ids')
    def _compute_message_count(self):
        for run in self:
            run.message_count = len(run.command_ids)


class FlowRecipe(models.Model):
    _name = 'mi.flow.recipe'
    _description = 'Marketing workflow recipe'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    sequence = fields.Integer(default=10)
    icon = fields.Char(default='flash_on')
    trigger = fields.Selection(TRIGGERS, required=True)
    keyword = fields.Char()
    steps = fields.Json(help='[[action, message, note], ...]')

    def action_use(self):
        self.ensure_one()
        brand = self.env['mi.brand'].browse(self.env.context.get('default_brand_id')).exists() or \
            self.env['mi.brand'].search([], limit=1)
        if not brand:
            raise UserError(_('Create a brand first.'))
        flow = self.env['mi.flow'].create({
            'name': self.name, 'brand_id': brand.id, 'trigger': self.trigger, 'keyword': self.keyword,
            'step_ids': [(0, 0, {'sequence': index, 'action': action, 'message': message or False,
                                 'note': note or False})
                         for index, (action, message, note) in enumerate(self.steps or [])],
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.flow', 'res_id': flow.id, 'view_mode': 'form',
                'views': [(False, 'form')], 'target': 'current'}
