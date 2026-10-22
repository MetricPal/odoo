from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.contact import CHANNELS, SOURCES


class ConsentWizard(models.TransientModel):
    _name = 'mm.consent.wizard'
    _description = 'Record opt-in or opt-out'

    contact_ids = fields.Many2many('mm.contact', string='Contacts', required=True)
    channel = fields.Selection(CHANNELS, required=True, default='whatsapp')
    action = fields.Selection([('opt_in', 'Opted in: agreed to receive marketing messages'),
                               ('opt_out', 'Opted out: does not want marketing messages')],
                              required=True, default='opt_in', string='The person')
    source = fields.Selection(SOURCES, required=True, default='form', string='How')
    evidence = fields.Text(
        string='Evidence',
        help='Where, when and to what the person agreed, with a reference: e.g. “Newsletter checkbox on the '
             'website sign-up form, 3 Oct 2026, order S00042”.')

    @api.onchange('action')
    def _onchange_action(self):
        if self.action == 'opt_out' and self.source == 'form':
            self.source = 'customer_request'

    def action_record(self):
        self.ensure_one()
        if not self.contact_ids:
            raise UserError(_('Choose at least one contact.'))
        self.contact_ids._record_consent(self.channel, self.action, self.source, self.evidence)
        return {'type': 'ir.actions.act_window_close'}


class ContactImport(models.TransientModel):
    _name = 'mm.contact.import'
    _description = 'Add contacts from Contacts'

    partner_ids = fields.Many2many('res.partner', string='Contacts', required=True,
                                   domain="[('phone', '!=', False)]")
    list_id = fields.Many2one('mm.list', string='Add to list')
    skipped = fields.Text(readonly=True)

    def action_import(self):
        """Create (or reuse) a messaging contact per partner. Never records an opt-in."""
        self.ensure_one()
        Contact = self.env['mm.contact']
        contacts = Contact
        skipped = []
        for partner in self.partner_ids:
            existing = Contact.search([('partner_id', '=', partner.id), ('company_id', '=', self.env.company.id)],
                                      limit=1)
            number = partner.phone and Contact._phone_format(
                number=partner.phone, country=partner.country_id or self.env.company.country_id,
                force_format='E164', raise_exception=False)
            if not existing and number:
                existing = Contact.search([('whatsapp', '=', number), ('company_id', '=', self.env.company.id)], limit=1)
            if not existing:
                if not number:
                    skipped.append(_('%(name)s: “%(phone)s” is not a valid mobile number',
                                     name=partner.display_name, phone=partner.phone or ''))
                    continue
                existing = Contact.create({
                    'name': partner.name or partner.display_name, 'partner_id': partner.id, 'whatsapp': number,
                    'country_id': partner.country_id.id, 'lang': partner.lang,
                })
            contacts |= existing
        if self.list_id:
            present = self.list_id.subscription_ids.contact_id
            self.env['mm.subscription'].create([{'list_id': self.list_id.id, 'contact_id': contact.id}
                                                for contact in contacts - present])
        message = _('%s contact(s) added. They have no opt-in yet: record how each person agreed before '
                    'sending them marketing.', len(contacts))
        if skipped:
            message += '\n' + _('Skipped: %s', '; '.join(skipped))
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'warning' if skipped else 'success', 'title': _('Contacts added'), 'message': message,
            'sticky': bool(skipped), 'next': {'type': 'ir.actions.act_window_close'},
        }}
