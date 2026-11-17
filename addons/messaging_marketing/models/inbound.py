"""Inbound messages from Omnichannel: STOP replies, replies to a mailing, delivery reports, and adding chats as
contacts."""

import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.omni_channel.models.inbox import internal as inbox_internal

from .trace import REACHED, REPLY_DAYS

# Whole-message replies that withdraw marketing consent on that channel.
STOP_WORDS = {'STOP', 'STOP ALL', 'STOPALL', 'UNSUBSCRIBE', 'BERHENTI'}
CHANNEL_CODES = ('whatsapp', 'telegram')


def is_stop(body):
    words = re.sub(r'[^\w ]+', ' ', (body or '').upper()).split()
    return ' '.join(words) in STOP_WORDS


def whatsapp_number(key):
    digits = re.sub(r'\D', '', key or '')
    return '+' + digits if digits else False


class InboundMessage(models.Model):
    _inherit = 'omni.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        for message in messages:
            if is_stop(message.body):
                message.sudo()._mm_opt_out()
            else:
                message.sudo()._mm_reply()
        return messages

    def _mm_contacts(self):
        """``(channel code, marketing contacts)`` of the person who wrote this message."""
        conversation = self.conversation_id
        channel = conversation.channel_id.channel_type_id.code
        if channel not in CHANNEL_CODES:
            return channel, self.env['mm.contact']
        key = conversation.identity_id.external_key
        domain = [('company_id', '=', self.company_id.id)]
        if channel == 'telegram':
            domain.append(('telegram_chat', '=', key))
        else:
            domain.append(('whatsapp', '=', whatsapp_number(key)))
        return channel, self.env['mm.contact'].sudo().search(domain)

    def _mm_reply(self):
        """An answer within a week of a mailing counts as a reply to the latest one the person received."""
        channel, contacts = self._mm_contacts()
        if not contacts:
            return
        since = (self.occurred_at or fields.Datetime.now()) - timedelta(days=REPLY_DAYS)
        trace = self.env['mm.trace'].sudo().search([
            ('contact_id', 'in', contacts.ids), ('channel', '=', channel), ('state', 'in', REACHED),
            ('mailing_id.channel_id', '=', self.conversation_id.channel_id.id),
            ('sent_at', '>=', since)], order='sent_at desc, id desc', limit=1)
        if trace and trace.state != 'replied':
            trace._mark_replied(self)

    def _mm_opt_out(self):
        """Record the reply as an opt-out for the matching marketing contact, if any."""
        conversation = self.conversation_id
        channel, contacts = self._mm_contacts()
        contacts = contacts.filtered(lambda c: c[channel + '_status'] != 'opted_out')
        if contacts:
            contacts._record_consent(channel, 'opt_out', 'keyword', _(
                'Replied “%(text)s” on %(channel)s at %(time)s UTC (message %(key)s).',
                text=(self.body or '').strip()[:40], channel=conversation.channel_id.name,
                time=self.occurred_at, key=self.external_key))


class WebhookEvent(models.Model):
    _inherit = 'omni.webhook.event'

    @api.model
    def _store(self, endpoint, event, raw_hash):
        """A channel's report about a mailing message (delivered, read, failed) goes to its recipient line.

        Reports about anything else stay as Omnichannel keeps them.
        """
        record = super()._store(endpoint, event, raw_hash)
        if (event.kind == 'receipt' and record.state == 'unresolved'
                and record.reason_code == 'receipt_reconciliation_pending' and event.message_key):
            command = self.env['omni.command'].sudo().search([
                ('channel_id', '=', endpoint.channel_id.id), ('provider_message_key', '=', event.message_key),
                ('mm_trace_id', '!=', False)], limit=1)
            if command:
                when = fields.Datetime.to_datetime(event.occurred_at) if event.occurred_at else False
                command.mm_trace_id._report(event.body, when)
                inbox_internal(record).write({'state': 'processed', 'reason_code': False})
        return record


class Conversation(models.Model):
    _inherit = 'omni.conversation'

    mm_channel_code = fields.Char(related='channel_id.channel_type_id.code', string='Channel kind')

    def action_mm_add_contact(self):
        """Add (or find) the Messaging Marketing contact for this chat. Never records an opt-in."""
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('messaging_marketing.group_mm_user'):
            raise AccessError(_('You need Messaging Marketing access to add contacts.'))
        channel = self.channel_id.channel_type_id.code
        if channel not in CHANNEL_CODES:
            raise UserError(_('Only WhatsApp and Telegram chats can be added to Messaging Marketing.'))
        key = self.identity_id.external_key
        Contact = self.env['mm.contact']
        partner = self.identity_id._visible_partner()
        if channel == 'telegram':
            contact = Contact.search([('company_id', '=', self.company_id.id), ('telegram_chat', '=', key)], limit=1)
            values = {'telegram_chat': key, 'telegram_conversation_id': self.id}
            if contact:
                contact.with_context(mm_telegram_link=True).write(values)
            else:
                contact = Contact.with_context(mm_telegram_link=True).create(dict(
                    values, name=partner.name or _('Telegram %s', key), partner_id=partner.id or False,
                    company_id=self.company_id.id))
        else:
            number = whatsapp_number(key)
            contact = Contact.search([('company_id', '=', self.company_id.id), ('whatsapp', '=', number)], limit=1)
            if not contact:
                contact = Contact.create({'name': partner.name or number, 'whatsapp': number,
                                          'partner_id': partner.id or False, 'company_id': self.company_id.id})
        contact.message_post(body=_('Linked to the %(channel)s conversation %(chat)s. No opt-in is recorded: '
                                    'ask the person and record how they agreed.',
                                    channel=self.channel_id.name, chat=key))
        return {'type': 'ir.actions.act_window', 'res_model': 'mm.contact', 'res_id': contact.id,
                'view_mode': 'form', 'target': 'current'}
