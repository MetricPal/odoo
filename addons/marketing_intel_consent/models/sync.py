"""Changes made in the sending apps come back into the ledger.

* Messaging consents (WhatsApp, Telegram) recorded on a Messaging contact.
* Email and phone blacklist entries (Email/SMS unsubscribe links, manual blacklisting) and removals.

Writes coming from the ledger itself carry ``mi_consent_sync`` and are not mirrored back.
"""

from odoo import _, models

from .consent import normalize_phone


class MessagingContact(models.Model):
    _inherit = 'mm.contact'

    def _record_consent(self, channel, action, source, evidence):
        records = super()._record_consent(channel, action, source, evidence)
        if not self.env.context.get('mi_consent_sync'):
            Subject = self.env['mi.consent.subject']
            for contact in self:
                subject = Subject._find_or_create(phone=contact.whatsapp, partner=contact.partner_id,
                                                  name=contact.name, company=contact.company_id)
                subject._record(channel, action, 'keyword' if source == 'keyword' else 'messaging',
                                evidence, propagate=False)
        return records


class MailBlacklist(models.Model):
    _inherit = 'mail.blacklist'

    def _add(self, email, message=None):
        record = super()._add(email, message=message)
        if not self.env.context.get('mi_consent_sync'):
            subject = self.env['mi.consent.subject']._find_or_create(email=email)
            subject._record('email', 'opt_out', 'unsubscribe', message or _('Added to the email blacklist.'),
                            propagate=False)
        return record

    def _remove(self, email, message=None):
        record = super()._remove(email, message=message)
        if not self.env.context.get('mi_consent_sync'):
            subject = self.env['mi.consent.subject']._find_or_create(email=email)
            subject._record('email', 'opt_in', 'unsubscribe', message or _('Removed from the email blacklist.'),
                            propagate=False)
        return record


class PhoneBlacklist(models.Model):
    _inherit = 'phone.blacklist'

    def _add(self, numbers, message=None):
        records = super()._add(numbers, message=message)
        if not self.env.context.get('mi_consent_sync'):
            for number in numbers:
                subject = self.env['mi.consent.subject']._find_or_create(phone=normalize_phone(number))
                subject._record('sms', 'opt_out', 'unsubscribe', message or _('Added to the phone blacklist.'),
                                propagate=False)
        return records

    def _remove(self, numbers, message=None):
        records = super()._remove(numbers, message=message)
        if not self.env.context.get('mi_consent_sync'):
            for number in numbers:
                subject = self.env['mi.consent.subject']._find_or_create(phone=normalize_phone(number))
                subject._record('sms', 'opt_in', 'unsubscribe', message or _('Removed from the phone blacklist.'),
                                propagate=False)
        return records
