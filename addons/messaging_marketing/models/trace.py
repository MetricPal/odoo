"""One row per recipient of a mailing, mirroring its Omnichannel message.

Each queued recipient becomes an ``omni.command`` sent by the existing
dispatch worker. The command carries a link to its trace; the worker accepts
the mailing's review as the command's approval and the person's opt-in as
recipient authorization (both re-checked just before sending).
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.omni_channel.models.command import is_internal

from .contact import CHANNELS

TRACE_STATES = [
    ('pending', 'Preparing'),
    ('queued', 'Waiting to send'),
    ('sending', 'Sending'),
    ('sent', 'Sent'),
    ('failed', 'Not sent'),
    ('unknown', 'Outcome unknown'),
    ('held', 'Held'),
    ('expired', 'Expired'),
    ('skipped', 'Skipped'),
    ('cancelled', 'Cancelled'),
]
# Omnichannel message status → recipient status.
COMMAND_STATES = {
    'queued': 'queued', 'dispatching': 'sending', 'accepted': 'sent', 'unknown': 'unknown',
    'failed': 'failed', 'held': 'held', 'expired': 'expired', 'cancelled': 'cancelled',
}
REASONS = {
    'invalid_recipient': 'The person blocked the bot, closed their account, or is not on the channel\'s test list.',
    'rate_limited': 'The provider limited the sending rate; retries ran out.',
    'unauthorized': 'The provider refused the channel credentials. An administrator must check the sender.',
    'unhealthy': 'The sender failed its health check.',
    'unsupported': 'This channel cannot send messages.',
    'transport': 'The provider could not be reached.',
}


class Trace(models.Model):
    _name = 'mm.trace'
    _description = 'Messaging mailing recipient'
    _order = 'id'
    _rec_name = 'address'

    mailing_id = fields.Many2one('mm.mailing', required=True, readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='mailing_id.company_id', store=True)
    purpose_id = fields.Many2one(related='mailing_id.purpose_id', store=True)
    contact_id = fields.Many2one('mm.contact', readonly=True, ondelete='set null', index=True)
    contact_name = fields.Char(related='contact_id.name', string='Contact')
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    address = fields.Char(required=True, readonly=True, string='Number or chat')
    state = fields.Selection(TRACE_STATES, required=True, default='pending', readonly=True, index=True,
                             string='Status')
    command_id = fields.Many2one('omni.command', readonly=True, ondelete='set null', string='Omnichannel message')
    note = fields.Char(readonly=True, string='Details')
    sent_at = fields.Datetime(readonly=True, string='Sent on')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Recipients are added when an approved mailing is sent.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Recipient results are recorded by the sending process.'))
        result = super().write(vals)
        if 'state' in vals:
            self.mailing_id._check_done()
        return result

    def unlink(self):
        if not self.env.su:
            raise AccessError(_('Mailing results are kept.'))
        return super().unlink()

    def _sync_from_command(self, command):
        state = COMMAND_STATES.get(command.state)
        if not state or state == self.state:
            return
        values = {'state': state}
        if state == 'sent':
            values.update(sent_at=fields.Datetime.now(), note=False)
        elif state in ('failed', 'held', 'expired', 'unknown'):
            code = command.current_attempt_id.reason_code if command.current_attempt_id else ''
            values['note'] = _(REASONS[code]) if code in REASONS else (command.held_reason or False)
        self.write(values)


class Command(models.Model):
    _inherit = 'omni.command'

    mm_trace_id = fields.Many2one('mm.trace', readonly=True, copy=False, ondelete='set null',
                                  index='btree_not_null', string='Mailing recipient')

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('mm_trace_id') for vals in vals_list) and not is_internal(self):
            raise AccessError(_('Mailing messages are created by an approved mailing.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'mm_trace_id' in vals and not is_internal(self):
            raise AccessError(_('Mailing messages are created by an approved mailing.'))
        result = super().write(vals)
        if 'state' in vals:
            for command in self.sudo().filtered('mm_trace_id'):
                command.mm_trace_id._sync_from_command(command)
        return result

    def copy(self, default=None):
        if self.mm_trace_id:
            raise AccessError(_('Duplicate the mailing instead of one of its messages.'))
        return super().copy(default)

    def _approval_targets_command(self, request):
        if self.mm_trace_id:
            mailing = self.mm_trace_id.sudo().mailing_id
            return (
                request == mailing.approval_request_id
                and request.mm_mailing_id == mailing
                and request.target_model == 'mm.mailing'
                and request.target_res_id == mailing.id
                and mailing.state in ('sending', 'done')
            )
        return super()._approval_targets_command(request)

    def _check_recipient_authorization(self):
        if self.mm_trace_id:
            trace = self.mm_trace_id.sudo()
            contact = trace.contact_id
            reason = contact._send_refusal(trace.channel, self.recipient) if contact else _('The contact was deleted.')
            if reason or trace.address != self.recipient:
                raise AccessError(reason or _('The recipient does not match the approved mailing.'))
            return
        super()._check_recipient_authorization()
