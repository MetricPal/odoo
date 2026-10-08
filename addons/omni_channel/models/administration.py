from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class OmniAdministration(models.Model):
    _inherit = "omni.channel"

    adapter_ready = fields.Boolean(related='channel_type_id.adapter_ready')

    connection_status = fields.Char(compute="_compute_operations_summary")
    inbound_status = fields.Char(compute="_compute_operations_summary")
    attention = fields.Char(compute="_compute_operations_summary")

    @api.depends(
        "sender_ids.health",
        "sender_ids.is_selected",
        "sender_ids.account_id.active",
        "endpoint_ids.state",
        "endpoint_ids.health",
        "dispatch_enabled",
        "active",
    )
    def _compute_operations_summary(self):
        for channel in self:
            sender = channel.selected_sender_id
            channel.connection_status = (
                _("Verified")
                if sender and sender.account_id.active and sender.health == "healthy"
                else _("Connection needs verification")
            )
            enabled = channel.endpoint_ids.filtered(
                lambda endpoint: endpoint.state == "enabled",
            )
            channel.inbound_status = _(
                "%(enabled)s of %(total)s enabled",
                enabled=len(enabled),
                total=len(channel.endpoint_ids),
            )
            issues = []
            if channel.readiness != "ready":
                issues.append(_("Sender or adapter needs attention"))
            if len(enabled) != len(
                channel.endpoint_ids,
            ) or channel.endpoint_ids.filtered(
                lambda endpoint: endpoint.health == "unhealthy",
            ):
                issues.append(_("Receiving endpoints need attention"))
            if not channel.dispatch_enabled:
                issues.append(_("Outbound dispatch paused"))
            channel.attention = "; ".join(issues) or _("No configuration warnings")

    @api.model
    def action_open_workspace(self):
        if not self.env.user.has_group('omni_channel.group_omni_user'):
            raise AccessError(_('Omni-Channel access is required.'))
        action = ('omni_channel.action_channels'
                  if self.env.user.has_group('base.group_system')
                  else 'omni_channel.action_inbox')
        return self.env['ir.actions.actions']._for_xml_id(action)

    def _open_administration(self, xmlid, domain, defaults=None):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only system administrators can configure channel infrastructure.'))
        self._require_manager()
        action = self.env['ir.actions.actions']._for_xml_id(xmlid)
        action.update(domain=domain, context=dict(self.env.context, **(defaults or {})))
        return action

    def action_connections(self):
        self.ensure_one()
        scope = {'company_id': self.company_id.id, 'purpose_id': self.purpose_id.id,
                 'channel_type_id': self.channel_type_id.id}
        return self._open_administration('omni_channel.action_omni_account',
            [(key, '=', value) for key, value in scope.items()],
            {'default_' + key: value for key, value in scope.items()})

    def action_messages(self):
        return self._open_administration('omni_channel.action_message_monitoring',
            [('channel_id', '=', self.id)], {'default_channel_id': self.id})

    def action_policies(self):
        return self._open_administration('omni_channel.action_inbound_policies',
            [('channel_id', '=', self.id)], {'default_channel_id': self.id})

    def action_delivery_logs(self):
        return self._open_administration('omni_channel.action_attempts',
            [('command_id.channel_id', '=', self.id)])

    def action_intake_logs(self):
        return self._open_administration('omni_channel.action_events',
            [('endpoint_id.channel_id', '=', self.id)])

    def action_recipient_authorizations(self):
        return self._open_administration('omni_channel.action_consent',
            [('channel_id', '=', self.id)], {'default_channel_id': self.id})

    def action_audit_logs(self):
        return self._open_administration('omni_channel.action_omni_audit_event',
            [('company_id', '=', self.company_id.id), ('purpose_id', '=', self.purpose_id.id)])


class OmniBlockConfiguration(models.Model):
    _inherit = 'omni.blocked.identity'
    _rec_name = 'external_key'

    connection_id = fields.Many2one(
        'omni.account', string='Connection', ondelete='restrict', check_company=True,
        help='Select the provider account this number or identity belongs to.',
    )

    @api.model
    def _connection_defaults(self, values):
        values = dict(values)
        if values.get('connection_id'):
            account = self.env['omni.account'].browse(values['connection_id'])
            account.check_access('read')
            for name, value in {
                'company_id': account.company_id.id,
                'purpose_id': account.purpose_id.id,
                'channel_type_id': account.channel_type_id.id,
                'namespace': account.namespace,
            }.items():
                values.setdefault(name, value)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._connection_defaults(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._connection_defaults(vals))

    @api.onchange('connection_id')
    def _onchange_connection(self):
        if self.connection_id:
            account = self.connection_id
            self.company_id = account.company_id
            self.purpose_id = account.purpose_id
            self.channel_type_id = account.channel_type_id
            self.namespace = account.namespace

    @api.constrains('connection_id', 'company_id', 'purpose_id', 'channel_type_id', 'namespace')
    def _check_connection_scope(self):
        for block in self:
            account = block.connection_id
            if account and (
                block.company_id != account.company_id
                or block.channel_type_id != account.channel_type_id
                or block.namespace != account.namespace
                or (block.purpose_id and block.purpose_id != account.purpose_id)
            ):
                raise ValidationError(_('The block must use the selected connection’s company, channel type and account scope.'))
