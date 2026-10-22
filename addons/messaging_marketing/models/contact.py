"""Audience for Messaging Marketing: contacts, their opt-in per channel, lists and blacklist.

Consent is evidence, not a checkbox: every opt-in and opt-out is an
append-only record saying who recorded it, when, how the person agreed, and
in which words. A contact's current status per channel is the latest record.
Nobody is ever sent a marketing message without a current opt-in, and a
blacklisted address is never sent to, whatever its opt-in says.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

CHANNELS = [('whatsapp', 'WhatsApp'), ('telegram', 'Telegram')]
STATUSES = [('unknown', 'No answer yet'), ('opted_in', 'Opted in'), ('opted_out', 'Opted out')]
SOURCES = [
    ('form', 'Signed up on a form'),
    ('in_person', 'Agreed in person'),
    ('message', 'Asked by message'),
    ('keyword', 'Keyword reply (e.g. STOP)'),
    ('import', 'Imported with recorded consent'),
    ('customer_request', 'Customer request'),
    ('other', 'Other'),
]


def manager(env):
    return env.user.has_group('messaging_marketing.group_mm_manager')


class Contact(models.Model):
    _name = 'mm.contact'
    _description = 'Messaging contact'
    _inherit = ['mail.thread']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Linked contact', ondelete='set null', check_company=True,
                                 help='The Contacts record of this person, if any.')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    country_id = fields.Many2one('res.country', help='Used to read local phone numbers.')
    whatsapp = fields.Char(string='WhatsApp number', tracking=True,
                           help='Mobile number in international format, e.g. +60 12 345 6789.')
    telegram_chat = fields.Char(string='Telegram chat ID', tracking=True, readonly=True,
                                help='Filled when the person starts your bot; Telegram has no phone lookup.')
    telegram_conversation_id = fields.Many2one(
        'omni.conversation', string='Telegram conversation', readonly=True, ondelete='set null',
        help='The bot conversation this person started. Telegram mailings are sent in this conversation.')
    lang = fields.Selection(lambda self: self.env['res.lang'].get_installed(), string='Language')
    active = fields.Boolean(default=True)
    subscription_ids = fields.One2many('mm.subscription', 'contact_id', string='Lists')
    list_ids = fields.Many2many('mm.list', compute='_compute_list_ids', search='_search_list_ids', string='In lists')
    consent_ids = fields.One2many('mm.consent', 'contact_id', string='Opt-in history', readonly=True)
    whatsapp_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='WhatsApp')
    telegram_status = fields.Selection(STATUSES, compute='_compute_status', store=True, string='Telegram')
    whatsapp_blacklisted = fields.Boolean(compute='_compute_blacklisted', search='_search_whatsapp_blacklisted',
                                          string='WhatsApp blacklisted')
    telegram_blacklisted = fields.Boolean(compute='_compute_blacklisted', search='_search_telegram_blacklisted',
                                          string='Telegram blacklisted')

    _whatsapp_unique = models.UniqueIndex('(company_id, whatsapp) WHERE whatsapp IS NOT NULL AND active',
                                          'Another contact already uses this WhatsApp number.')
    _telegram_unique = models.UniqueIndex('(company_id, telegram_chat) WHERE telegram_chat IS NOT NULL AND active',
                                          'Another contact already uses this Telegram chat.')

    # ------------------------------------------------------------------ numbers

    def _normalize_whatsapp(self, number, country=None):
        if not number:
            return False
        formatted = self._phone_format(number=number, country=country or self.env.company.country_id,
                                       force_format='E164', raise_exception=False)
        if not formatted:
            raise ValidationError(_('“%s” is not a valid mobile number. Use the international format, '
                                    'e.g. +60 12 345 6789.', number))
        return formatted

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('whatsapp'):
                country = self.env['res.country'].browse(vals.get('country_id')) if vals.get('country_id') else None
                vals['whatsapp'] = self._normalize_whatsapp(vals['whatsapp'], country)
            if not self.env.context.get('mm_telegram_link'):
                vals.pop('telegram_chat', None)
                vals.pop('telegram_conversation_id', None)
        contacts = super().create(vals_list)
        list_id = self.env.context.get('mm_list_id')
        if list_id:
            self.env['mm.subscription'].create([{'list_id': list_id, 'contact_id': c.id} for c in contacts])
        return contacts

    def write(self, vals):
        if {'telegram_chat', 'telegram_conversation_id'} & vals.keys() and not self.env.context.get('mm_telegram_link'):
            raise AccessError(_('The Telegram chat is linked when the person starts your bot.'))
        if vals.get('whatsapp'):
            for contact in self:
                country = self.env['res.country'].browse(vals['country_id']) if vals.get('country_id') else contact.country_id
                super(Contact, contact).write(dict(vals, whatsapp=self._normalize_whatsapp(vals['whatsapp'], country)))
            return True
        return super().write(vals)

    # ------------------------------------------------------------------ lists

    def _compute_list_ids(self):
        for contact in self:
            contact.list_ids = contact.subscription_ids.filtered(lambda s: not s.opt_out).list_id

    def _search_list_ids(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        subscribed = [('subscription_ids', 'any', [('list_id', 'in', value), ('opt_out', '=', False)])]
        return subscribed if operator == 'in' else ['!'] + subscribed

    # ------------------------------------------------------------------ consent

    @api.depends('consent_ids.action', 'consent_ids.channel', 'consent_ids.recorded_at')
    def _compute_status(self):
        for contact in self:
            for channel, _label in CHANNELS:
                latest = contact.consent_ids.filtered(lambda c: c.channel == channel).sorted(
                    lambda c: (c.recorded_at, c.id), reverse=True)[:1]
                status = {'opt_in': 'opted_in', 'opt_out': 'opted_out'}.get(latest.action, 'unknown')
                contact[channel + '_status'] = status

    def _address(self, channel):
        self.ensure_one()
        return self.whatsapp if channel == 'whatsapp' else self.telegram_chat

    def _compute_blacklisted(self):
        Blacklist = self.env['mm.blacklist'].sudo()
        for contact in self:
            for channel, _label in CHANNELS:
                address = contact._address(channel)
                contact[channel + '_blacklisted'] = bool(address) and bool(Blacklist.search_count([
                    ('company_id', '=', contact.company_id.id), ('channel', '=', channel),
                    ('address', '=', address)], limit=1))

    def _search_blacklisted(self, channel, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        rows = self.env['mm.blacklist'].sudo().search_read([('channel', '=', channel)], ['address', 'company_id'])
        field = 'whatsapp' if channel == 'whatsapp' else 'telegram_chat'
        addresses = [row['address'] for row in rows]
        positive = (True in value) == (operator == 'in')
        return [(field, 'in', addresses)] if positive else ['|', (field, '=', False), (field, 'not in', addresses)]

    def _search_whatsapp_blacklisted(self, operator, value):
        return self._search_blacklisted('whatsapp', operator, value)

    def _search_telegram_blacklisted(self, operator, value):
        return self._search_blacklisted('telegram', operator, value)

    def _can_receive(self, channel):
        """True when this contact may be sent marketing on ``channel`` right now."""
        self.ensure_one()
        return (self.active and bool(self._address(channel)) and self[channel + '_status'] == 'opted_in'
                and not self[channel + '_blacklisted'])

    def _send_refusal(self, channel, address):
        """Why a marketing message to ``address`` must not be sent now, or '' when it may.

        Checked when a mailing queues its messages and again by the dispatch
        worker just before each one is sent.
        """
        self.ensure_one()
        if not self.active:
            return _('The contact is archived.')
        if self._address(channel) != address:
            return _('The number or chat changed after the mailing was approved.')
        # Read the blacklist itself: an address added a moment ago must stop the message.
        if self.env['mm.blacklist'].sudo().search_count([
                ('company_id', '=', self.company_id.id), ('channel', '=', channel), ('address', '=', address)],
                limit=1):
            return _('The address is blacklisted.')
        status = self[channel + '_status']
        if status == 'opted_out':
            return _('The person opted out.')
        if status != 'opted_in':
            return _('The person has no opt-in on this channel.')
        if channel == 'telegram' and not self.telegram_conversation_id:
            return _('The person has not started a conversation with the bot.')
        return ''

    def _record_consent(self, channel, action, source, evidence):
        """The only way consent changes: one new evidence record per contact."""
        if channel not in dict(CHANNELS) or action not in ('opt_in', 'opt_out') or source not in dict(SOURCES):
            raise UserError(_('Choose a channel, what the person said and how.'))
        evidence = (evidence or '').strip()
        if action == 'opt_in' and len(evidence) < 10:
            raise UserError(_('Describe how the person agreed (at least a short sentence): where, when, and to what.'))
        self.check_access('write')
        for contact in self:
            if action == 'opt_in' and not contact._address(channel):
                raise UserError(_('%(name)s has no %(channel)s address yet.',
                                  name=contact.name, channel=dict(CHANNELS)[channel]))
        records = self.env['mm.consent'].sudo().with_context(mm_consent_write=True).create([{
            'contact_id': contact.id, 'channel': channel, 'action': action, 'source': source,
            'evidence': evidence or _('Opted out.'), 'recorded_by': self.env.uid,
        } for contact in self])
        for contact, record in zip(self, records):
            contact.message_post(body=_('%(channel)s: %(action)s — %(source)s.',
                                        channel=dict(CHANNELS)[channel],
                                        action=_('opted in') if action == 'opt_in' else _('opted out'),
                                        source=dict(record._fields['source']._description_selection(self.env))[source]))
        return records

    def action_record_consent(self):
        return {
            'type': 'ir.actions.act_window', 'res_model': 'mm.consent.wizard', 'view_mode': 'form',
            'views': [(False, 'form')], 'target': 'new', 'name': _('Record opt-in or opt-out'),
            'context': {'default_contact_ids': self.ids},
        }


class Consent(models.Model):
    _name = 'mm.consent'
    _description = 'Messaging opt-in evidence'
    _order = 'recorded_at desc, id desc'
    _rec_name = 'contact_id'

    contact_id = fields.Many2one('mm.contact', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='contact_id.company_id', store=True)
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    action = fields.Selection([('opt_in', 'Opted in'), ('opt_out', 'Opted out')], required=True, readonly=True)
    source = fields.Selection(SOURCES, required=True, readonly=True, string='How')
    evidence = fields.Text(required=True, readonly=True)
    recorded_by = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user)
    recorded_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('mm_consent_write'):
            raise AccessError(_('Use “Record opt-in or opt-out” on the contact.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Opt-in history is kept as recorded. Record a new opt-in or opt-out instead.'))

    def unlink(self):
        if not self.env.su:
            raise AccessError(_('Opt-in history is kept as evidence.'))
        return super().unlink()


class MarketingList(models.Model):
    _name = 'mm.list'
    _description = 'Messaging list'
    _inherit = ['omni.scope.mixin']
    _order = 'name'

    purpose_id = fields.Many2one(default=lambda self: self._default_marketing_team())
    name = fields.Char(required=True)
    description = fields.Text(help='Who is in this list and what they signed up for.')
    active = fields.Boolean(default=True)
    subscription_ids = fields.One2many('mm.subscription', 'list_id', string='Members')
    contact_count = fields.Integer(compute='_compute_counts', string='Contacts')
    whatsapp_count = fields.Integer(compute='_compute_counts', string='Reachable on WhatsApp')
    telegram_count = fields.Integer(compute='_compute_counts', string='Reachable on Telegram')

    def _default_marketing_team(self):
        team = self.env.ref('omni_channel.purpose_marketing', raise_if_not_found=False)
        return team if team and team.active else False

    def _compute_counts(self):
        for row in self:
            members = row.subscription_ids.filtered(lambda s: not s.opt_out).contact_id.filtered('active')
            row.contact_count = len(members)
            row.whatsapp_count = len(members.filtered(lambda c: c._can_receive('whatsapp')))
            row.telegram_count = len(members.filtered(lambda c: c._can_receive('telegram')))

    def action_view_contacts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'mm.contact',
                'view_mode': 'list,form', 'domain': [('list_ids', 'in', self.ids)],
                'context': {'mm_list_id': self.id}}


class Subscription(models.Model):
    _name = 'mm.subscription'
    _description = 'Messaging list membership'
    _rec_name = 'contact_id'

    list_id = fields.Many2one('mm.list', required=True, ondelete='cascade', index=True)
    contact_id = fields.Many2one('mm.contact', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='list_id.company_id', store=True)
    opt_out = fields.Boolean(string='Left this list', help='The person asked to leave this list only.')
    left_at = fields.Datetime(readonly=True, string='Left on')
    _pair_unique = models.Constraint('UNIQUE(list_id, contact_id)', 'This contact is already in the list.')

    @api.constrains('list_id', 'contact_id')
    def _check_company(self):
        for row in self:
            if row.list_id.company_id != row.contact_id.company_id:
                raise ValidationError(_('A list and its contacts belong to the same company.'))

    def write(self, vals):
        if vals.get('opt_out'):
            vals['left_at'] = fields.Datetime.now()
        elif 'opt_out' in vals:
            vals['left_at'] = False
        return super().write(vals)


class Blacklist(models.Model):
    _name = 'mm.blacklist'
    _description = 'Messaging blacklist'
    _order = 'create_date desc, id desc'
    _rec_name = 'address'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    channel = fields.Selection(CHANNELS, required=True)
    address = fields.Char(required=True, string='Number or chat ID')
    reason = fields.Char(required=True, default=lambda self: _('Asked not to be contacted'))
    _address_unique = models.Constraint('UNIQUE(company_id, channel, address)', 'This address is already blacklisted.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('channel') == 'whatsapp' and vals.get('address'):
                vals['address'] = self.env['mm.contact']._normalize_whatsapp(vals['address'])
        entries = super().create(vals_list)
        self.env['mm.contact'].invalidate_model(['whatsapp_blacklisted', 'telegram_blacklisted'])
        return entries

    def unlink(self):
        if not manager(self.env):
            raise AccessError(_('Only a Messaging Marketing administrator can remove an address from the blacklist.'))
        result = super().unlink()
        self.env['mm.contact'].invalidate_model(['whatsapp_blacklisted', 'telegram_blacklisted'])
        return result
