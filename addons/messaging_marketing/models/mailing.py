"""Mailings: one reviewed message sent to the opted-in members of lists.

Flow: draft → submitted for review (text, channel and the exact recipient
list are frozen and hashed) → approved → sent right away or at the scheduled
time. Sending creates one Omnichannel message per recipient, queued for the
existing dispatch worker. The worker checks each message again just before
sending: this mailing's approval, the channel's approvers, and the person's
current opt-in and blacklist status. Nothing is sent from this module itself.
"""

import ipaddress
import re
from datetime import timedelta
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.mail import TEXT_URL_REGEX

from odoo.addons.approval_center.models.common import capability
from odoo.addons.omni_channel.models.command import digest
from odoo.addons.omni_channel.models.command import internal as omni_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.providers.base import installed_adapters

from .contact import CHANNELS

internal, trusted = capability('_mm_internal')

# Longest text each channel accepts in one message.
LIMITS = {'telegram': 4096, 'whatsapp': 1024}
PLACEHOLDERS = ('{first_name}', '{name}')
STATES = [
    ('draft', 'Draft'),
    ('pending', 'Waiting for approval'),
    ('approved', 'Approved'),
    ('sending', 'Sending'),
    ('done', 'Sent'),
    ('refused', 'Refused'),
    ('cancelled', 'Cancelled'),
]


def guarded(records, names, values):
    if not trusted(records) and protected_input(records, names, values):
        raise AccessError(_('Use the mailing actions to change its review status.'))


def public_base(url):
    """True when short links on this address can be opened from the internet."""
    parts = urlsplit(url or '')
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host or host == 'localhost' or host.endswith('.local'):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return '.' in host


def render(template, contact):
    """Fill the placeholders for one person. Plain text only: no code is evaluated."""
    name = (contact.name or '').strip()
    first = name.split()[0] if name else ''
    return (template or '').replace('{first_name}', first).replace('{name}', name)


class Mailing(models.Model):
    _name = 'mm.mailing'
    _description = 'Messaging mailing'
    _inherit = ['omni.scope.mixin', 'mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, tracking=True, string='Title',
                       help='For your team only; not sent to recipients.')
    purpose_id = fields.Many2one(default=lambda self: self.env['mm.list']._default_marketing_team())
    channel = fields.Selection(CHANNELS, required=True, default=lambda self: self._default_channel(), tracking=True)
    channel_id = fields.Many2one(
        'omni.channel', string='Send from', check_company=True, ondelete='restrict',
        domain="[('company_id', '=', company_id), ('purpose_id', '=', purpose_id), "
               "('channel_type_id.code', '=', channel)]",
        help='The Omnichannel channel (bot or business number) that sends this mailing.')
    body = fields.Text(string='Message', tracking=True)
    list_ids = fields.Many2many('mm.list', string='Send to lists',
                                domain="[('company_id', '=', company_id), ('purpose_id', '=', purpose_id)]")
    reason = fields.Text(string='Note for the approver',
                         help='Why this mailing goes out and anything the approver should check. Not sent.')
    schedule = fields.Selection([('now', 'Right after approval'), ('later', 'At a date and time')],
                                string='Send', required=True, default='now')
    scheduled_at = fields.Datetime(string='Send at', tracking=True)
    track_links = fields.Boolean(default=True, string='Track links',
                                 help='Links become short links that count clicks for this mailing.')
    utm_campaign_id = fields.Many2one('utm.campaign', string='Campaign',
                                      help='Report clicks, leads and sales from this mailing under a campaign.')
    source_id = fields.Many2one('utm.source', readonly=True, copy=False, string='Tracking source')
    currency_id = fields.Many2one(related='company_id.currency_id')
    price_per_message = fields.Monetary(
        string='Price per message', currency_field='currency_id',
        help='What the provider charges per marketing message (WhatsApp charges per conversation and country). '
             'Used only for the estimate.')

    requester_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user,
                                   string='Prepared by')
    state = fields.Selection(STATES, required=True, default='draft', readonly=True, copy=False, index=True,
                             tracking=True)
    approval_request_id = fields.Many2one('approval.center.request', readonly=True, copy=False,
                                          ondelete='restrict')
    payload = fields.Json(readonly=True, copy=False)
    payload_hash = fields.Char(readonly=True, copy=False)
    policy_hash = fields.Char(readonly=True, copy=False)
    expires_at = fields.Datetime(readonly=True, copy=False, string='Approval valid until')
    sent_at = fields.Datetime(readonly=True, copy=False, string='Sending started')
    trace_ids = fields.One2many('mm.trace', 'mailing_id', readonly=True, string='Recipients')

    # Audience and checks (live in draft; from the frozen list once submitted)
    audience_count = fields.Integer(compute='_compute_audience', string='Will receive')
    member_count = fields.Integer(compute='_compute_audience', string='List members')
    excluded_no_address = fields.Integer(compute='_compute_audience', string='No address on this channel')
    excluded_no_answer = fields.Integer(compute='_compute_audience', string='No opt-in yet')
    excluded_opted_out = fields.Integer(compute='_compute_audience', string='Opted out')
    excluded_blacklisted = fields.Integer(compute='_compute_audience', string='Blacklisted')
    excluded_no_chat = fields.Integer(compute='_compute_audience', string='No bot conversation')
    excluded_summary = fields.Char(compute='_compute_audience', string='Not included')
    cost_estimate = fields.Monetary(compute='_compute_audience', currency_field='currency_id',
                                    string='Estimated cost')
    char_count = fields.Integer(compute='_compute_text', string='Characters')
    char_limit = fields.Integer(compute='_compute_text')
    preview_text = fields.Text(compute='_compute_text', string='Preview')
    preview_name = fields.Char(compute='_compute_text')
    link_count = fields.Integer(compute='_compute_text')
    channel_problem = fields.Char(compute='_compute_channel_problem')
    display_state = fields.Char(compute='_compute_display_state', string='Status')
    is_requester = fields.Boolean(compute='_compute_is_requester')
    is_due = fields.Boolean(compute='_compute_is_requester')

    # Results
    recipient_count = fields.Integer(compute='_compute_results', string='Recipients')
    queued_count = fields.Integer(compute='_compute_results', string='Waiting to send')
    sent_count = fields.Integer(compute='_compute_results', string='Sent')
    failed_count = fields.Integer(compute='_compute_results', string='Not sent')
    skipped_count = fields.Integer(compute='_compute_results', string='Skipped')
    click_count = fields.Integer(compute='_compute_results', string='Link clicks')

    _protected = {'state', 'requester_id', 'approval_request_id', 'payload', 'payload_hash', 'policy_hash',
                  'expires_at', 'sent_at', 'source_id', 'company_id', 'purpose_id'}

    @api.constrains('scheduled_at', 'schedule')
    def _check_schedule(self):
        for row in self:
            if row.state == 'draft' and row.schedule == 'later' and not row.scheduled_at:
                raise ValidationError(_('Choose when to send, or send right after approval.'))

    # ------------------------------------------------------------------ CRUD

    @api.model_create_multi
    def create(self, vals_list):
        guarded(self, self._protected - {'company_id', 'purpose_id'}, vals_list)
        return super().create(vals_list)

    def write(self, vals):
        guarded(self, self._protected, [vals])
        if not trusted(self):
            for row in self:
                if row.state != 'draft' or row.requester_id != self.env.user:
                    raise AccessError(_('Only the person who prepared a draft can change it. '
                                        'Duplicate a submitted mailing to change it.'))
        return super().write(vals)

    def unlink(self):
        if any(row.state != 'draft' or row.requester_id != self.env.user for row in self):
            raise AccessError(_('Submitted mailings are kept with their review and results. Cancel them instead.'))
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        self.check_access('read')
        vals = {'name': _('%s (copy)', self.name), 'channel': self.channel, 'channel_id': self.channel_id.id,
                'body': self.body, 'list_ids': [fields.Command.set(self.list_ids.ids)], 'reason': self.reason,
                'track_links': self.track_links, 'utm_campaign_id': self.utm_campaign_id.id,
                'price_per_message': self.price_per_message, 'purpose_id': self.purpose_id.id}
        vals.update(default or {})
        return self.create(vals)

    def _lock(self):
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute('SELECT id FROM mm_mailing WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    # ------------------------------------------------------------------ defaults and onchange

    @api.model
    def _connector_sends(self, code):
        """Whether the installed Omnichannel connector for ``code`` can send messages at all."""
        factory = installed_adapters(self.env).get(code)
        if factory is None:
            return False
        supported = getattr(factory, 'dispatch_supported', None)
        if supported is None:
            try:
                supported = getattr(factory(), 'dispatch_supported', False)
            except Exception:  # noqa: BLE001 - an adapter that cannot start cannot send
                supported = False
        return bool(supported)

    @api.model
    def _default_channel(self):
        return 'telegram' if not self._connector_sends('whatsapp') else 'whatsapp'

    @api.onchange('channel', 'purpose_id', 'company_id')
    def _onchange_channel(self):
        if self.channel_id and (self.channel_id.channel_type_id.code != self.channel
                                or self.channel_id.purpose_id != self.purpose_id):
            self.channel_id = False
        if not self.channel_id and self.channel and self.purpose_id:
            self.channel_id = self.env['omni.channel'].search([
                ('company_id', '=', self.company_id.id), ('purpose_id', '=', self.purpose_id.id),
                ('channel_type_id.code', '=', self.channel), ('active', '=', True)], limit=1)
        if self.channel == 'telegram':
            self.price_per_message = 0

    # ------------------------------------------------------------------ audience

    def _members(self):
        self.ensure_one()
        subscriptions = self.list_ids.sudo().subscription_ids.filtered(lambda s: not s.opt_out)
        return subscriptions.contact_id.filtered(lambda c: c.active and c.company_id == self.company_id) \
            .with_env(self.env)

    def _classify(self, contacts):
        """Split contacts by why they can or cannot receive this mailing now."""
        self.ensure_one()
        channel = self.channel
        blacklisted = set(self.env['mm.blacklist'].sudo().search(
            [('company_id', '=', self.company_id.id), ('channel', '=', channel)]).mapped('address'))
        result = {'ok': contacts.browse(), 'no_address': 0, 'no_answer': 0, 'opted_out': 0, 'blacklisted': 0,
                  'no_chat': 0}
        for contact in contacts.sudo():
            address = contact._address(channel)
            status = contact[channel + '_status']
            if not address:
                result['no_address'] += 1
            elif address in blacklisted:
                result['blacklisted'] += 1
            elif status == 'opted_out':
                result['opted_out'] += 1
            elif status != 'opted_in':
                result['no_answer'] += 1
            elif channel == 'telegram' and not contact.telegram_conversation_id:
                result['no_chat'] += 1
            else:
                result['ok'] |= contact
        result['ok'] = result['ok'].with_env(self.env)
        return result

    @api.depends('list_ids', 'channel', 'state', 'payload', 'price_per_message')
    def _compute_audience(self):
        for row in self:
            if row.state != 'draft' and row.payload:
                frozen = row.payload.get('audience', {})
                row.update({
                    'audience_count': len(row.payload.get('recipients', [])),
                    'member_count': frozen.get('members', 0),
                    'excluded_no_address': frozen.get('no_address', 0),
                    'excluded_no_answer': frozen.get('no_answer', 0),
                    'excluded_opted_out': frozen.get('opted_out', 0),
                    'excluded_blacklisted': frozen.get('blacklisted', 0),
                    'excluded_no_chat': frozen.get('no_chat', 0),
                })
            else:
                members = row._members() if row.list_ids else self.env['mm.contact']
                split = row._classify(members) if members else {
                    'ok': members, 'no_address': 0, 'no_answer': 0, 'opted_out': 0, 'blacklisted': 0, 'no_chat': 0}
                row.update({
                    'audience_count': len(split['ok']), 'member_count': len(members),
                    'excluded_no_address': split['no_address'], 'excluded_no_answer': split['no_answer'],
                    'excluded_opted_out': split['opted_out'], 'excluded_blacklisted': split['blacklisted'],
                    'excluded_no_chat': split['no_chat'],
                })
            row.cost_estimate = row.audience_count * (row.price_per_message or 0.0)
            parts = [_('%s without an opt-in yet', row.excluded_no_answer) if row.excluded_no_answer else '',
                     _('%s opted out', row.excluded_opted_out) if row.excluded_opted_out else '',
                     _('%s blacklisted', row.excluded_blacklisted) if row.excluded_blacklisted else '',
                     _('%s without an address on this channel', row.excluded_no_address)
                     if row.excluded_no_address else '',
                     _('%s who have not started the bot', row.excluded_no_chat) if row.excluded_no_chat else '']
            parts = [part for part in parts if part]
            row.excluded_summary = (_('Out of %(members)s list members. Not included: %(reasons)s.',
                                      members=row.member_count, reasons=', '.join(parts)) if parts else
                                    _('Out of %s list members: everyone can receive it.', row.member_count))

    @api.depends('body', 'channel', 'list_ids')
    def _compute_text(self):
        for row in self:
            sample = row._members()[:1] if row.list_ids else self.env['mm.contact']
            sample_name = sample.sudo().name if sample else _('Aisha Rahman')
            fake = self.env['mm.contact'].new({'name': sample_name})
            row.preview_name = sample_name
            row.preview_text = render(row.body, fake) if row.body else ''
            row.char_limit = LIMITS.get(row.channel, 4096)
            row.char_count = len(row.preview_text)
            row.link_count = len(set(re.findall(TEXT_URL_REGEX, row.body or '')))

    @api.depends('channel', 'channel_id', 'channel_id.selected_sender_id.health', 'channel_id.dispatch_enabled')
    def _compute_channel_problem(self):
        for row in self:
            row.channel_problem = row._channel_problem(strict=False)

    def _channel_problem(self, strict=True):
        """Why this mailing cannot be sent from its channel, or ''.

        Not strict (form hint): only what the user must fix before submitting.
        Strict (submit and send): also a healthy selected sender.
        """
        self.ensure_one()
        label = dict(CHANNELS).get(self.channel, '')
        if not self._connector_sends(self.channel):
            return _('%s sending is not available yet: the Omnichannel connector only receives messages. '
                     'You can prepare the audience now.', label)
        if not self.channel_id:
            return _('Choose the %(channel)s channel to send from. An Omnichannel administrator connects one for '
                     'the %(team)s team.', channel=label, team=self.purpose_id.name or _('marketing'))
        channel = self.channel_id.sudo()
        sender = channel.selected_sender_id
        if not sender or sender.health != 'healthy':
            return _('The channel has no verified sender. An Omnichannel administrator selects and checks one.')
        if not channel.approval_type_id:
            return _('The channel has no message approval type. An Omnichannel administrator chooses one.')
        if not channel.dispatch_enabled and not strict:
            return _('Sending is paused on this channel. Approved messages wait until an Omnichannel '
                     'administrator enables sending.')
        return ''

    @api.depends('state', 'schedule', 'scheduled_at')
    def _compute_display_state(self):
        labels = dict(self._fields['state']._description_selection(self.env))
        for row in self:
            if row.state == 'approved' and row.schedule == 'later' and row.scheduled_at:
                row.display_state = _('Scheduled')
            else:
                row.display_state = labels.get(row.state, '')

    @api.depends_context('uid')
    @api.depends('requester_id', 'schedule', 'scheduled_at')
    def _compute_is_requester(self):
        now = fields.Datetime.now()
        for row in self:
            row.is_requester = row.requester_id == self.env.user
            row.is_due = row.schedule == 'now' or bool(row.scheduled_at and row.scheduled_at <= now)

    @api.depends('trace_ids.state')
    def _compute_results(self):
        Click = self.env['link.tracker.click'].sudo()
        for row in self:
            states = row.trace_ids.mapped('state')
            row.recipient_count = len(states)
            row.queued_count = sum(s in ('queued', 'sending') for s in states)
            row.sent_count = states.count('sent')
            row.failed_count = sum(s in ('failed', 'held', 'expired', 'unknown', 'cancelled') for s in states)
            row.skipped_count = states.count('skipped')
            row.click_count = Click.search_count([('link_id.utm_reference', '=', f'{row._name},{row.id}')]) \
                if row.id else 0

    # ------------------------------------------------------------------ review

    def _policy(self):
        """The channel's approval type, checked like every Omnichannel message review."""
        self.ensure_one()
        policy = self.channel_id.sudo().approval_type_id
        if not policy or not policy.active or policy.company_id != self.company_id:
            raise UserError(_('The channel needs an active approval type for this company.'))
        if policy.manager_approval:
            raise UserError(_('Use explicitly assigned approvers for communication reviews.'))
        if policy.model and (policy.model != 'omni.command' or policy.action_name != 'action_enqueue_approved'):
            raise UserError(_('Use a general approval type or the Omnichannel message approval type.'))
        lines = policy.approver_ids.sorted(lambda line: (line.sequence, line.id))
        if not lines or policy.approval_minimum > len(lines):
            raise UserError(_('The approval type needs enough explicitly assigned approvers.'))
        for line in lines:
            user = line.user_id
            if (not user.active or user.share or user == self.requester_id
                    or user not in self.purpose_id.user_ids or self.company_id not in user.company_ids
                    or not user.has_group('approval_center.group_approval_center_approver')):
                raise UserError(_('Approvers must be other active internal members of the %s team with approval '
                                  'rights. You cannot approve your own mailing.', self.purpose_id.name))
        return {'id': policy.id, 'minimum': policy.approval_minimum, 'sequence': policy.approver_sequence,
                'version': fields.Datetime.to_string(policy.write_date),
                'approvers': [(line.user_id.id, line.sequence, line.required) for line in lines]}

    def _tracking_base(self):
        return self.env['ir.config_parameter'].sudo().get_str('web.base.url') or ''

    def _utm_values(self):
        Mixin = self.env['utm.mixin'].sudo()
        medium = Mixin._find_or_create_record('utm.medium', dict(CHANNELS)[self.channel])
        return {'campaign_id': self.utm_campaign_id.id, 'source_id': self.source_id.id, 'medium_id': medium.id,
                'utm_reference': f'{self._name},{self.id}', 'title': self.name}

    def _shorten_links(self):
        """Replace links by tracked short links before the text is frozen (users can only read trackers)."""
        if not self.track_links or not public_base(self._tracking_base()):
            return
        base = self._tracking_base().rstrip('/') + '/r/'
        if not [url for url in re.findall(TEXT_URL_REGEX, self.body or '') if not url.startswith(base)]:
            return
        body = self.env['mail.render.mixin'].sudo()._shorten_links_text(self.body, self._utm_values())
        if body != self.body:
            self.write({'body': body})

    def _check_ready(self):
        self.ensure_one()
        problems = []
        if not (self.body or '').strip():
            problems.append(_('Write the message.'))
        elif len(render(self.body, self.env['mm.contact'].new({'name': 'X' * 40}))) > LIMITS.get(self.channel, 4096):
            problems.append(_('The message is longer than %s characters.', LIMITS.get(self.channel, 4096)))
        if not self.list_ids:
            problems.append(_('Choose at least one list.'))
        if not (self.reason or '').strip():
            problems.append(_('Add a note for the approver.'))
        if self.schedule == 'later' and (not self.scheduled_at or self.scheduled_at <= fields.Datetime.now()):
            problems.append(_('Choose a sending time in the future.'))
        channel_problem = self._channel_problem(strict=True)
        if channel_problem:
            problems.append(channel_problem)
        if problems:
            raise UserError('\n'.join(problems))

    def _document(self):
        """Everything the approver approves. Recipients are the people reachable at submission."""
        self.ensure_one()
        members = self._members()
        split = self._classify(members)
        recipients = sorted([contact.id, contact.sudo()._address(self.channel)] for contact in split['ok'])
        if not recipients:
            raise UserError(_('Nobody in these lists can receive this mailing yet: they need an opt-in on %s.',
                              dict(CHANNELS)[self.channel]))
        channel = self.channel_id.sudo()
        return {
            'schema': 1, 'mailing': self.id, 'company': self.company_id.id, 'purpose': self.purpose_id.code,
            'channel': self.channel, 'channel_id': channel.id, 'generation': channel.generation,
            'sender': channel.selected_sender_id.external_key, 'body': self.body,
            'lists': sorted(self.list_ids.ids), 'recipients': recipients,
            'audience': {'members': len(members), **{k: v for k, v in split.items() if k != 'ok'}},
            'scheduled_at': fields.Datetime.to_string(self.scheduled_at) if self.schedule == 'later' else False,
            'utm': {'campaign': self.utm_campaign_id.id, 'source': self.source_id.id},
            'cost': {'price': self.price_per_message, 'currency': self.currency_id.name},
        }

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        self._lock()
        if self.state != 'draft' or self.requester_id != self.env.user:
            raise AccessError(_('Only the person who prepared this draft can submit it.'))
        self._check_ready()
        policy = self._policy()
        if not self.source_id:
            internal(self).write({'source_id': self.env['utm.source'].sudo().create({'name': self.name}).id})
        self._shorten_links()
        doc = self._document()
        request = internal(self.env['approval.center.request']).create({
            'name': self.name, 'policy_id': policy['id'], 'company_id': self.company_id.id,
            'requester_id': self.env.uid, 'mm_mailing_id': self.id, 'target_model': self._name,
            'target_res_id': self.id, 'reason': self.reason, 'state': 'submitted',
            'approver_ids': [fields.Command.create({'user_id': uid, 'sequence': sequence, 'required': required,
                                                    'status': 'submitted'})
                             for uid, sequence, required in policy['approvers']],
        })
        request._check_required_fields()
        request._audit('submitted', _('Mailing submitted for review.'))
        start = max(fields.Datetime.now(), self.scheduled_at) if self.schedule == 'later' else fields.Datetime.now()
        internal(self).write({
            'state': 'pending', 'approval_request_id': request.id, 'payload': doc, 'payload_hash': digest(doc),
            'policy_hash': digest(policy), 'expires_at': start + timedelta(hours=24),
        })
        self._audit('mm.submitted', _('Text, channel and %s recipients frozen for review.', len(doc['recipients'])))
        return self.action_view_approval()

    def _frozen(self):
        """The approved mailing is still exactly what was reviewed, and still allowed."""
        self.ensure_one()
        channel = self.channel_id.sudo()
        self.with_user(self.requester_id).with_context(allowed_company_ids=[self.company_id.id]) \
            .check_access('read')
        if (not self.requester_id.active or not self.payload or digest(self.payload) != self.payload_hash
                or not self.expires_at or self.expires_at <= fields.Datetime.now()
                or channel.generation != self.payload.get('generation')
                or channel.selected_sender_id.external_key != self.payload.get('sender')
                or self.body != self.payload.get('body')
                or digest(self._policy()) != self.policy_hash):
            raise UserError(_('This approval expired or the channel or its approvers changed. '
                              'Duplicate the mailing for a new review.'))

    def _approved_evidence(self):
        request = self.approval_request_id.sudo()
        policy = self._policy()
        approved = request.approver_ids.filtered(lambda line: line.status == 'approved')
        required = {uid for uid, sequence, needed in policy['approvers'] if needed}
        if (request.state != 'approved' or request.mm_mailing_id != self
                or len(approved) < policy['minimum'] or not required.issubset(set(approved.user_id.ids))):
            raise AccessError(_('This mailing has no valid approval.'))
        return request

    def action_view_approval(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'approval.center.request',
                'res_id': self.approval_request_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_cancel(self):
        for row in self:
            row.check_access('read')
            row._lock()
            if row.requester_id != self.env.user and not self.env.user.has_group(
                    'messaging_marketing.group_mm_manager'):
                raise AccessError(_('Only the person who prepared the mailing or an administrator can cancel it.'))
            if row.state not in ('draft', 'pending', 'approved', 'sending'):
                raise UserError(_('This mailing can no longer be cancelled.'))
            if row.state == 'sending':
                # Messages not yet handed to the provider are withdrawn; sent ones stay sent.
                for trace in row.trace_ids.filtered(lambda t: t.state == 'queued').sudo():
                    command = trace.command_id
                    if command and command.state == 'queued':
                        omni_internal(command).write({'state': 'cancelled', 'held_reason': _('Mailing cancelled.')})
                    trace.write({'state': 'cancelled', 'note': _('Mailing cancelled before sending.')})
            if row.approval_request_id.state == 'submitted':
                request = row.approval_request_id.sudo()
                internal(request).write({'state': 'refused'})
                request._audit('refused', _('Withdrawn: the mailing was cancelled before review.'))
            internal(row).write({'state': 'cancelled'})
            row._audit('mm.cancelled', _('Mailing cancelled.'))
        return True

    def action_duplicate(self):
        self.ensure_one()
        copy = self.copy()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': copy.id, 'view_mode': 'form',
                'target': 'current'}

    # ------------------------------------------------------------------ sending

    def action_send_now(self):
        self.ensure_one()
        self.check_access('read')
        if self.requester_id != self.env.user and not self.env.user.has_group('messaging_marketing.group_mm_manager'):
            raise AccessError(_('Only the person who prepared the mailing or an administrator can send it.'))
        if self.schedule == 'later' and self.scheduled_at and self.scheduled_at > fields.Datetime.now():
            raise UserError(_('This mailing is scheduled for %s. It is sent automatically then.',
                              fields.Datetime.to_string(self.scheduled_at)))
        self.sudo()._start_sending()
        return True

    def _start_sending(self):
        """Queue one Omnichannel message per frozen recipient who can still receive it."""
        self.ensure_one()
        self._lock()
        if self.state != 'approved':
            raise UserError(_('Only an approved mailing that has not been sent can be sent.'))
        self._frozen()
        request = self._approved_evidence()
        channel = self.channel_id.sudo()
        sender = channel.selected_sender_id
        problem = self._channel_problem(strict=True)
        if problem:
            raise UserError(problem)
        Trace = self.env['mm.trace'].sudo()
        Contact = self.env['mm.contact'].sudo().with_context(active_test=False)
        Command = omni_internal(self.env['omni.command'].sudo())
        now = fields.Datetime.now()
        command_policy = None
        for contact_id, address in self.payload['recipients']:
            contact = Contact.browse(contact_id).exists()
            trace = Trace.create({'mailing_id': self.id, 'contact_id': contact.id or False, 'address': address,
                                  'channel': self.channel})
            reason = contact._send_refusal(self.channel, address) if contact else _('The contact was deleted.')
            if reason:
                trace.write({'state': 'skipped', 'note': reason})
                continue
            body = render(self.body, contact)
            command = Command.create({
                'name': self.name, 'channel_id': channel.id, 'recipient': address, 'body': body,
                'reason': self.reason, 'requester_id': self.requester_id.id, 'mm_trace_id': trace.id,
                'conversation_id': contact.telegram_conversation_id.id if self.channel == 'telegram' else False,
            })
            command = command.with_user(self.requester_id).sudo()
            if command_policy is None:
                command_policy = digest(command._policy_document())
            payload = {
                'schema': 1, 'uuid': command.uuid, 'company': command.company_id.id,
                'purpose': command.purpose_id.code, 'channel': channel.id, 'generation': channel.generation,
                'sender': sender.external_key, 'account': sender.account_id.external_account_key,
                'recipient': address, 'body': body, 'operation': 'message.send', **command._extra_payload(),
            }
            omni_internal(command).write({
                'state': 'queued', 'sender_id': sender.id, 'channel_generation': channel.generation,
                'payload': payload, 'payload_hash': digest(payload), 'policy_hash': command_policy,
                'expires_at': now + timedelta(hours=24), 'approval_request_id': request.id,
            })
            command._audit('message.queued', _('Queued from an approved mailing.'))
            trace.write({'state': 'queued', 'command_id': command.id})
        internal(self).write({'state': 'sending', 'sent_at': now})
        internal(request).write({'executed_at': now})
        self._audit('mm.sending', _('Approved mailing queued for sending.'))
        self._check_done()

    def _check_done(self):
        for row in self.filtered(lambda r: r.state == 'sending'):
            if not row.trace_ids.filtered(lambda t: t.state in ('queued', 'sending')):
                internal(row).write({'state': 'done'})

    @api.model
    def _cron_send_scheduled(self, limit=20):
        """Start approved mailings whose time has come (immediate ones are started on approval)."""
        due = self.sudo().search([('state', '=', 'approved'), ('schedule', '=', 'later'),
                                  ('scheduled_at', '<=', fields.Datetime.now())], limit=limit)
        for mailing in due:
            try:
                with self.env.cr.savepoint():
                    mailing._start_sending()
            except (UserError, AccessError) as error:
                mailing.message_post(body=_('Scheduled sending did not start: %s', error))
                internal(mailing).write({'state': 'cancelled'})
                mailing._audit('mm.cancelled', _('Scheduled sending could not start.'))

    def action_view_traces(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Recipients: %s', self.name), 'res_model': 'mm.trace',
                'view_mode': 'list,graph', 'domain': [('mailing_id', '=', self.id)],
                'context': {'search_default_group_state': 1, 'create': False}}

    def action_view_clicks(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Clicks: %s', self.name),
                'res_model': 'link.tracker.click', 'view_mode': 'list,graph',
                'domain': [('link_id.utm_reference', '=', f'{self._name},{self.id}')], 'context': {'create': False}}
