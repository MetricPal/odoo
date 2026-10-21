"""Routing comes only from authenticated personal activities; never from user input."""

import hashlib
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.omni_channel.models.command import internal, is_internal
from odoo.addons.omni_channel.models.foundation import protected_input
from odoo.addons.omni_channel.providers.inbound import reject
from ..providers import webhook
from ..providers.adapter import bundle

ROUTE = {'teams_service_url', 'teams_member_id', 'teams_app_id', 'teams_member_name'}


class TeamsConversation(models.Model):
    _inherit = 'omni.conversation'

    teams_member_name = fields.Char(readonly=True, copy=False)

    @api.depends('teams_member_name', 'thread_key')
    def _compute_display_name(self):
        super()._compute_display_name()
        for conversation in self:
            if conversation.channel_id.channel_type_id.code == 'teams' and conversation.teams_member_name:
                conversation.display_name = conversation.teams_member_name

    teams_service_url = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    teams_member_id = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')
    teams_app_id = fields.Char(readonly=True, copy=False, groups='omni_channel.group_omni_manager')

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, ROUTE, vals_list) and not is_internal(self):
            raise AccessError(_('Teams routing is recorded by verified intake.'))
        return super().create(vals_list)

    def write(self, values):
        if protected_input(self, ROUTE, [values]) and not is_internal(self):
            raise AccessError(_('Teams routing is recorded by verified intake.'))
        return super().write(values)

    def _teams_route(self):
        self.ensure_one()
        self.check_access('read')
        record = self.sudo()
        if (
            self.channel_id.channel_type_id.code != 'teams'
            or not record.teams_service_url
            or not record.teams_member_id
        ):
            raise UserError(_('Choose a verified Teams personal chat.'))
        return {
            'thread': self.thread_key,
            'identity': self.identity_id.external_key,
            'service_url': record.teams_service_url,
            'member_id': record.teams_member_id,
            'app_id': record.teams_app_id,
        }


class TeamsEndpoint(models.Model):
    _inherit = 'omni.inbound.endpoint'

    def _receive(self, raw, headers):
        if self.channel_type_id.code != 'teams':
            return super()._receive(raw, headers)
        if not self.env.su:
            raise AccessError(_('Only verified transport may receive activities.'))
        if not self._allowed():
            reject('disabled')
        try:
            credentials = bundle(self._config())
            value = webhook.authenticate(raw, headers, credentials['app_id'], credentials['tenant_id'])
            key, message = webhook.message(value)
        except Exception:
            reject('verification')
        result = super()._receive(raw, headers)
        if message:
            event = self.env['omni.webhook.event'].search(
                [('endpoint_id', '=', self.id), ('event_hash', '=', hashlib.sha256(key.encode()).hexdigest())], limit=1
            )
            # One bounded private-text normalization within the HTTP transaction.
            # This records its routing in the same commit as the authenticated text.
            event._process_one()
            if event.state == 'processed' and not event.collision:
                conversation = self.env['omni.conversation'].search(
                    [
                        ('endpoint_id', '=', self.id),
                        ('ownership_version', '=', self.ownership_version),
                        ('thread_key', '=', message['thread']),
                        ('identity_id.external_key', '=', message['user']),
                    ],
                    limit=1,
                )
                if conversation:
                    internal(conversation).write(
                        {
                            'teams_service_url': message['service_url'],
                            'teams_member_id': message['member_id'],
                            'teams_app_id': credentials['app_id'],
                            'teams_member_name': str(value.get('from', {}).get('name', message['user']))[:128],
                        }
                    )
        return result


class TeamsCommand(models.Model):
    _inherit = 'omni.command'

    def _extra_payload(self):
        result = super()._extra_payload()
        if self.channel_id.channel_type_id.code == 'teams' and self.conversation_id:
            result['conversation'].update(self.conversation_id._teams_route())
        return result
