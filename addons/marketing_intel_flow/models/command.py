"""Workflow messages go through Omnichannel like any approved message.

A workflow's approval (one review for many messages) is accepted as the
evidence for the messages it queues — the extension point Omnichannel offers
for exactly this — while the channel's approver list, its policy and the
person's current opt-in are still checked right before each message is sent.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.omni_channel.models.command import is_internal


class Command(models.Model):
    _inherit = 'omni.command'

    mi_flow_run_id = fields.Many2one('mi.flow.run', readonly=True, copy=False, ondelete='set null',
                                     index='btree_not_null', string='Marketing workflow run')

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('mi_flow_run_id') for vals in vals_list) and not is_internal(self):
            raise AccessError(_('Workflow messages are created by an approved workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'mi_flow_run_id' in vals and not is_internal(self):
            raise AccessError(_('Workflow messages are created by an approved workflow.'))
        return super().write(vals)

    def copy(self, default=None):
        if self.mi_flow_run_id:
            raise AccessError(_('Workflow messages cannot be duplicated.'))
        return super().copy(default)

    def _approval_targets_command(self, request):
        if self.mi_flow_run_id:
            flow = self.mi_flow_run_id.sudo().flow_id
            return (
                request == flow.approval_request_id
                and request.target_model == 'mi.flow'
                and request.target_res_id == flow.id
                and flow.state == 'active'
                and flow._digest() == flow.approved_digest
                and flow._channel() == self.channel_id
            )
        return super()._approval_targets_command(request)

    def _check_recipient_authorization(self):
        if self.mi_flow_run_id:
            run = self.mi_flow_run_id.sudo()
            contact = run.mm_contact_id
            code = self.channel_id.sudo().channel_type_id.code
            reason = contact._send_refusal(code, self.recipient) if contact else _('The contact was deleted.')
            if reason:
                raise AccessError(reason)
            return
        super()._check_recipient_authorization()
