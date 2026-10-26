"""Consent ledger: one record per person per channel, append-only, with source and evidence.

A *subject* is a person as marketing knows them (contact, email, phone). Every
opt-in or opt-out is a new ledger record; the current status per channel is the
latest record. Opt-outs are pushed to the places that actually stop messages:
the email and phone blacklists (Email and SMS marketing) and Messaging consents
(WhatsApp, Telegram). Changes made there come back into the ledger (see sync.py).
"""

import hashlib
import re
import secrets

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError

CHANNELS = [('email', 'Email'), ('sms', 'SMS'), ('whatsapp', 'WhatsApp'), ('telegram', 'Telegram'),
            ('social', 'Social private messages')]
STATUSES = [('unknown', 'No answer yet'), ('opted_in', 'Opted in'), ('opted_out', 'Opted out')]
SOURCES = [('form', 'Signed up on a form'), ('preference_page', 'Preference page'),
           ('unsubscribe', 'Unsubscribe link or blacklist'), ('keyword', 'Keyword reply (e.g. STOP)'),
           ('messaging', 'Messaging consent'), ('staff', 'Recorded by staff'), ('import', 'Imported'),
           ('data_request', 'Data request')]


def normalize_phone(phone):
    phone = (phone or '').strip()
    digits = re.sub(r'\D', '', phone)
    return ('+' + digits) if phone.startswith('+') and digits else digits


class Topic(models.Model):
    _name = 'mi.consent.topic'
    _description = 'Marketing topic'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)


class Subject(models.Model):
    _name = 'mi.consent.subject'
    _description = 'Person (consent)'
    _inherit = ['mail.thread']
    _order = 'write_date desc, id desc'

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', string='Contact', index=True)
    email = fields.Char(index=True)
    phone = fields.Char(index=True, help='International format, e.g. +60123456789')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    token = fields.Char(readonly=True, copy=False, index=True, groups='marketing_intel.group_mi_manager',
                        default=lambda self: secrets.token_urlsafe(24))
    record_ids = fields.One2many('mi.consent.record', 'subject_id', string='History')
    email_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='Email consent')
    sms_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='SMS consent')
    whatsapp_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='WhatsApp consent')
    telegram_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='Telegram consent')
    social_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='Social DM consent')
    topic_ids = fields.Many2many('mi.consent.topic', compute='_compute_status', string='Topics')
    last_change = fields.Datetime(compute='_compute_status', store=True)
    erased = fields.Boolean(readonly=True, copy=False)

    _email_unique = models.UniqueIndex('(company_id, lower(email)) WHERE email IS NOT NULL AND email != \'\'',
                                       'This email already belongs to another person.')

    @api.depends('record_ids.action', 'record_ids.channel', 'record_ids.topic_id', 'record_ids.recorded_at')
    def _compute_status(self):
        for subject in self:
            latest, topics = {}, {}
            for record in subject.record_ids.sorted(lambda r: (r.recorded_at, r.id)):
                if record.topic_id:
                    topics[record.topic_id.id] = record.action
                else:
                    latest[record.channel] = record.action
            for channel, _label in CHANNELS:
                action = latest.get(channel)
                subject[f'{channel}_status'] = {'opt_in': 'opted_in', 'opt_out': 'opted_out'}.get(action, 'unknown')
            subject.topic_ids = [(6, 0, [tid for tid, action in topics.items() if action == 'opt_in'])]
            subject.last_change = max(subject.record_ids.mapped('recorded_at'), default=False)

    # ------------------------------------------------------------------ finding people

    @api.model
    def _find_or_create(self, email=None, phone=None, partner=None, name=None, company=None):
        company = company or self.env.company
        email = tools.email_normalize(email or (partner and partner.email) or '') or False
        phone = normalize_phone(phone or (partner and (partner.phone or getattr(partner, 'mobile', ''))) or '') or False
        Subject = self.sudo().with_context(active_test=False)
        domain = [('company_id', '=', company.id)]
        subject = Subject.browse()
        if partner:
            subject = Subject.search(domain + [('partner_id', '=', partner.id)], limit=1)
        if not subject and email:
            subject = Subject.search(domain + [('email', '=ilike', email)], limit=1)
        if not subject and phone:
            subject = Subject.search(domain + [('phone', '=', phone)], limit=1)
        if subject:
            values = {}
            if partner and not subject.partner_id:
                values['partner_id'] = partner.id
            if email and not subject.email:
                values['email'] = email
            if phone and not subject.phone:
                values['phone'] = phone
            if values:
                subject.write(values)
            return subject
        return Subject.create({'name': name or (partner and partner.name) or email or phone or _('Unknown'),
                               'partner_id': partner.id if partner else False, 'email': email, 'phone': phone,
                               'company_id': company.id})

    # ------------------------------------------------------------------ recording

    def _record(self, channel, action, source, evidence='', topic=False, propagate=True):
        """Append one ledger record per subject and stop or allow messages where it matters."""
        if channel not in dict(CHANNELS) or action not in ('opt_in', 'opt_out') or source not in dict(SOURCES):
            raise UserError(_('Choose a channel, what the person said and how.'))
        if action == 'opt_in' and source == 'staff' and len((evidence or '').strip()) < 10:
            raise UserError(_('Describe how the person agreed (where, when, to what).'))
        Record = self.env['mi.consent.record'].sudo().with_context(mi_consent_write=True)
        records = Record.create([{'subject_id': s.id, 'channel': channel, 'action': action, 'source': source,
                                  'evidence': (evidence or '').strip() or _('No details given.'),
                                  'topic_id': topic.id if topic else False, 'recorded_by': self.env.uid}
                                 for s in self])
        if propagate and not topic:
            for subject in self:
                subject.sudo()._propagate(channel, action, source, evidence)
        return records

    def _propagate(self, channel, action, source, evidence):
        """Make the ledger effective in the apps that send: blacklists and Messaging consents."""
        sync = self.with_context(mi_consent_sync=True)
        note = _('Consent ledger: %s', evidence or dict(SOURCES)[source])
        by_person = source in ('preference_page', 'form', 'keyword')
        if channel == 'email' and self.email:
            if action == 'opt_out':
                sync.env['mail.blacklist'].sudo()._add(self.email, message=note)
            elif by_person:
                sync.env['mail.blacklist'].sudo()._remove(self.email, message=note)
        elif channel == 'sms' and self.phone and 'phone.blacklist' in self.env:
            if action == 'opt_out':
                sync.env['phone.blacklist'].sudo()._add([self.phone], message=note)
            elif by_person:
                sync.env['phone.blacklist'].sudo()._remove([self.phone], message=note)
        elif channel in ('whatsapp', 'telegram') and 'mm.contact' in self.env:
            mm_source = {'keyword': 'keyword', 'form': 'form', 'preference_page': 'customer_request'}.get(
                source, 'customer_request' if action == 'opt_out' else None)
            if not mm_source:
                return
            for contact in self._mm_contacts():
                if action == 'opt_in' and not contact._address(channel):
                    continue
                contact.with_context(mi_consent_sync=True).sudo()._record_consent(
                    channel, action, mm_source, evidence or _('From the consent ledger (%s).', dict(SOURCES)[source]))

    def _mm_contacts(self):
        if 'mm.contact' not in self.env:
            return self.env['res.partner'].browse()
        Contact = self.env['mm.contact'].sudo()
        contacts = Contact.browse()
        if self.partner_id:
            contacts |= Contact.search([('partner_id', '=', self.partner_id.id), ('company_id', '=', self.company_id.id)])
        if self.phone:
            contacts |= Contact.search([('company_id', '=', self.company_id.id)]).filtered(
                lambda c: normalize_phone(c.whatsapp) == self.phone)
        return contacts

    def _allows(self, channel):
        self.ensure_one()
        return self[f'{channel}_status'] != 'opted_out'

    # ------------------------------------------------------------------ preference page

    def _preference_url(self):
        self.ensure_one()
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return '%s/marketing/preferences/%s' % (base.rstrip('/'), self.sudo().token)

    def _apply_preferences(self, wanted_channels, wanted_topics, evidence, unsubscribe_all=False):
        """What the person chose on the page; only changes are recorded."""
        self.ensure_one()
        for channel, _label in CHANNELS:
            want = False if unsubscribe_all else channel in wanted_channels
            status = self[f'{channel}_status']
            if want and status != 'opted_in':
                self._record(channel, 'opt_in', 'preference_page', evidence)
            elif not want and status == 'opted_in' or (unsubscribe_all and status != 'opted_out'):
                self._record(channel, 'opt_out', 'preference_page', evidence)
        Topic = self.env['mi.consent.topic'].sudo()
        for topic in Topic.search([('company_id', 'in', [False, self.company_id.id])]):
            want = False if unsubscribe_all else topic.id in wanted_topics
            if want != (topic in self.topic_ids):
                self._record('email', 'opt_in' if want else 'opt_out', 'preference_page', evidence, topic=topic)
        self.message_post(body=_('Preferences changed on the preference page.'))

    def action_open_preferences(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self._preference_url(), 'target': 'new'}

    def action_record(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.consent.wizard', 'view_mode': 'form',
                'target': 'new', 'context': {'default_subject_id': self.id}}

    def action_request_data(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'mi.data.request', 'view_mode': 'form',
                'target': 'current', 'context': {'default_subject_id': self.id}}

    # ------------------------------------------------------------------ first install

    @api.model
    def _backfill(self):
        """Bring existing Messaging consents and blacklists into the ledger once."""
        Record = self.env['mi.consent.record'].sudo().with_context(mi_consent_write=True)
        if 'mm.consent' in self.env:
            for consent in self.env['mm.consent'].sudo().search([], order='recorded_at, id'):
                contact = consent.contact_id
                subject = self._find_or_create(phone=contact.whatsapp, partner=contact.partner_id,
                                               name=contact.name, company=contact.company_id)
                Record.create({'subject_id': subject.id, 'channel': consent.channel, 'action': consent.action,
                               'source': 'messaging', 'evidence': consent.evidence, 'recorded_at': consent.recorded_at,
                               'recorded_by': consent.recorded_by.id})
        for entry in self.env['mail.blacklist'].sudo().search([]):
            subject = self._find_or_create(email=entry.email)
            Record.create({'subject_id': subject.id, 'channel': 'email', 'action': 'opt_out', 'source': 'import',
                           'evidence': _('Already on the email blacklist when the ledger started.')})


class Record(models.Model):
    _name = 'mi.consent.record'
    _description = 'Consent record'
    _order = 'recorded_at desc, id desc'
    _rec_name = 'subject_id'

    subject_id = fields.Many2one('mi.consent.subject', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='subject_id.company_id', store=True)
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    topic_id = fields.Many2one('mi.consent.topic', readonly=True, string='Topic')
    action = fields.Selection([('opt_in', 'Opted in'), ('opt_out', 'Opted out')], required=True, readonly=True)
    source = fields.Selection(SOURCES, required=True, readonly=True, string='How')
    evidence = fields.Text(required=True, readonly=True)
    recorded_by = fields.Many2one('res.users', readonly=True, default=lambda self: self.env.user)
    recorded_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('mi_consent_write'):
            raise AccessError(_('Record consent from the person, the preference page or the apps that send.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Consent history is kept as recorded. Record a new opt-in or opt-out instead.'))

    def unlink(self):
        raise AccessError(_('Consent history cannot be deleted; an erasure request anonymizes the person.'))


class ConsentWizard(models.TransientModel):
    _name = 'mi.consent.wizard'
    _description = 'Record consent'

    subject_id = fields.Many2one('mi.consent.subject', required=True)
    channel = fields.Selection(CHANNELS, required=True, default='email')
    action = fields.Selection([('opt_in', 'Opted in'), ('opt_out', 'Opted out')], required=True, default='opt_out')
    source = fields.Selection([('staff', 'Told us directly'), ('form', 'Signed up on a form'),
                               ('import', 'Imported with recorded consent')], required=True, default='staff')
    evidence = fields.Text(help='Where, when and to what the person agreed or said no.')

    def action_save(self):
        self.ensure_one()
        self.subject_id._record(self.channel, self.action, self.source, self.evidence)
        return {'type': 'ir.actions.act_window_close'}


def anonymous_hash(value):
    return hashlib.sha256((value or '').strip().lower().encode()).hexdigest()[:16]
