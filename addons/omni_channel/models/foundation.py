import re
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.omni_channel.providers.base import (
    AdapterUnavailable,
    get_adapter,
    installed_adapters,
)


def protected_input(records, names, vals_list):
    """ORM default_* context is client-controlled input too."""
    return any(names & vals.keys() for vals in vals_list) or any(
        'default_' + name in records.env.context for name in names
    )


class OmniPurpose(models.Model):
    _name = 'omni.purpose'
    _description = 'Communication Purpose'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    user_ids = fields.Many2many(
        'res.users', string='Authorized team', domain=[('share', '=', False)],
    )
    _code_unique = models.Constraint('UNIQUE(code)', 'Purpose codes must be unique.')

    @api.constrains('user_ids')
    def _check_internal_team(self):
        if self.user_ids.filtered('share'):
            raise ValidationError(
                _('Only internal users can belong to a communication team.'),
            )


class OmniChannelType(models.Model):
    _name = 'omni.channel.type'
    _description = 'Channel Catalog'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    category = fields.Selection(
        [('messaging', 'Messaging'), ('social', 'Social'), ('other', 'Other')],
        default='other', required=True,
    )
    sequence = fields.Integer(default=10)
    adapter_ready = fields.Boolean(
        compute='_compute_adapter_ready', string='Adapter installed',
    )
    _code_unique = models.Constraint('UNIQUE(code)', 'Channel codes must be unique.')

    def _compute_adapter_ready(self):
        available = installed_adapters(self.env)
        for record in self:
            record.adapter_ready = record.code in available


class OmniScope(models.AbstractModel):
    _name = 'omni.scope.mixin'
    _description = 'Omni Company and Purpose Boundary'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    purpose_id = fields.Many2one(
        'omni.purpose', required=True, ondelete='restrict', index=True,
        string='Communication team',
        help='The team and business purpose for this channel, for example Customer Support. Ordinary users need team membership and the appropriate Omni role.',
    )

    def _require_manager(self):
        self.check_access('write')
        if not self.env.user.has_group('omni_channel.group_omni_manager'):
            raise AccessError(
                _('Only an Omni-Channel administrator can change configuration.'),
            )

    @api.constrains('purpose_id', 'company_id')
    def _check_scope(self):
        for record in self:
            if not self.env.su:
                if (
                    record.company_id not in self.env.companies
                    or (
                        not self.env.user.has_group('base.group_system')
                        and self.env.user not in record.purpose_id.user_ids
                    )
                ):
                    raise AccessError(
                        _(
                            'This company or communication purpose is not available to you.',
                        ),
                    )

    def _audit(self, event, detail):
        self.ensure_one()
        # The caller has already passed action and record authorization. Only the
        # ledger insertion is elevated; it cannot be invoked through public RPC.
        self.env['omni.audit.event'].sudo().create(
            {
                'company_id': self.company_id.id,
                'purpose_id': self.purpose_id.id,
                'actor_id': self.env.uid,
                'event': event,
                'resource': f'{self._name},{self.id}',
                'detail': detail,
            },
        )


class OmniChannel(models.Model):
    _name = 'omni.channel'
    _inherit = ['omni.scope.mixin']
    _description = 'Communication Channel'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    channel_type_id = fields.Many2one(
        'omni.channel.type', required=True, ondelete='restrict',
    )
    generation = fields.Integer(default=0, readonly=True, copy=False)
    sender_ids = fields.One2many('omni.outbound.sender', 'channel_id')
    endpoint_ids = fields.One2many('omni.inbound.endpoint', 'channel_id')
    selected_sender_id = fields.Many2one(
        'omni.outbound.sender', compute='_compute_summary', string='Runtime sender',
    )
    sender_count = fields.Integer(compute='_compute_summary')
    endpoint_count = fields.Integer(compute='_compute_summary')
    readiness = fields.Selection(
        [
            ('unavailable', 'Adapter not installed'),
            ('unconfigured', 'Choose a sender'),
            ('ready', 'Ready'),
            ('blocked', 'Needs attention'),
        ],
        compute='_compute_summary',
    )
    _scope_unique = models.Constraint(
        'UNIQUE(company_id, purpose_id, channel_type_id)',
        'This company already has a channel for this purpose and channel type. Restore the archived channel instead.',
    )

    @api.depends(
        'sender_ids.is_selected',
        'sender_ids.health',
        'sender_ids.active',
        'endpoint_ids',
        'channel_type_id',
    )
    def _compute_summary(self):
        available = installed_adapters(self.env)
        for channel in self:
            selected = channel.sender_ids.filtered('is_selected')[:1]
            channel.selected_sender_id = selected
            channel.sender_count = len(channel.sender_ids)
            channel.endpoint_count = len(channel.endpoint_ids)
            channel.readiness = (
                'unavailable'
                if channel.channel_type_id.code not in available
                else 'unconfigured'
                if not selected
                else 'ready'
                if selected.health == 'healthy' and selected.active and channel.active
                else 'blocked'
            )

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, {'generation'}, vals_list):
            raise AccessError(_('Channel generation is managed by sender activation.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'generation' in vals:
            raise AccessError(_('Channel generation is managed by sender activation.'))
        if {'company_id', 'purpose_id', 'channel_type_id'} & vals.keys():
            for channel in self:
                if (
                    channel.with_context(active_test=False).sender_ids
                    or channel.with_context(active_test=False).endpoint_ids
                ):
                    raise UserError(
                        _('A configured channel cannot change ownership or type.'),
                    )
        return super().write(vals)

    def _lock(self):
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(
            'SELECT id FROM omni_channel WHERE id = %s FOR UPDATE', [self.id],
        )
        self.invalidate_recordset()

    def action_select_sender(self):
        self.ensure_one()
        self._require_manager()
        if not self.sender_ids:
            raise UserError(_('Add an outbound sender in the Outbound senders tab first.'))
        wizard = (
            self.env['omni.sender.selection'].create(
                {
                    'channel_id': self.id,
                    'expected_generation': self.generation,
                    'sender_id': self.selected_sender_id.id,
                },
            )
            if self.selected_sender_id
            else self.env['omni.sender.selection'].create(
                {
                    'channel_id': self.id,
                    'expected_generation': self.generation,
                    'sender_id': self.sender_ids[:1].id,
                },
            )
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'omni.sender.selection',
            'name': _('Select runtime sender'),
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _advance_generation(self):
        super().write({'generation': self.generation + 1})


class OmniAccount(models.Model):
    _name = 'omni.account'
    _inherit = ['omni.scope.mixin']
    _description = 'Provider Connection'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    channel_type_id = fields.Many2one(
        'omni.channel.type', required=True, ondelete='restrict',
    )
    external_account_key = fields.Char(
        required=True, string='Provider account ID',
        help='The provider-issued account identifier, not an Odoo user ID. Telegram fills its numeric bot ID from the provisioned secret reference. Other adapters define their own account identity.',
    )
    namespace = fields.Char(
        required=True,
        string='Account identity scope',
        help='Keeps external identities separate between provider accounts. Telegram uses the bot ID and fills it automatically; this value must match the connected provider account.',
    )
    credential_reference = fields.Char(
        groups='omni_channel.group_omni_manager',
        copy=False,
        help='Reference to a deployment-provisioned secret. Never enter a token here.',
    )
    _account_unique = models.Constraint(
        'UNIQUE(company_id, channel_type_id, external_account_key)',
        'This external account is already configured.',
    )

    def _adapter_config(self):
        self.ensure_one()
        return {}

    @api.constrains('credential_reference')
    def _check_reference(self):
        for account in self:
            if account.credential_reference and not re.fullmatch(
                r'OMNI_SECRET_[A-Z0-9_]{1,100}', account.credential_reference,
            ):
                raise ValidationError(
                    _(
                        'Use an OMNI_SECRET_ reference, not a credential value or file path.',
                    ),
                )

    def write(self, vals):
        protected = {
            'company_id',
            'purpose_id',
            'channel_type_id',
            'external_account_key',
            'namespace',
            'credential_reference',
            'active',
        }
        if protected & vals.keys():
            # Serialize with activation before checking selected senders.
            channels = (
                self.env['omni.outbound.sender']
                .sudo()
                .with_context(active_test=False)
                .search(
                    [
                        ('account_id', 'in', self.ids),
                    ],
                )
                .channel_id.sorted('id')
            )
            for channel in channels:
                channel._lock()
            if (
                self.env['omni.outbound.sender']
                .sudo()
                .search_count(
                    [('account_id', 'in', self.ids), ('is_selected', '=', True)],
                )
            ):
                raise UserError(
                    _('Deactivate the runtime sender before changing its connection.'),
                )
            if {
                'company_id',
                'purpose_id',
                'channel_type_id',
                'external_account_key',
                'namespace',
            } & vals.keys():
                for model in ('omni.outbound.sender', 'omni.inbound.endpoint'):
                    if (
                        self.env[model]
                        .sudo()
                        .with_context(active_test=False)
                        .search_count([('account_id', 'in', self.ids)])
                    ):
                        raise UserError(
                            _(
                                'A connection in use cannot change identity or ownership.',
                            ),
                        )
        return super().write(vals)


class OmniBinding(models.AbstractModel):
    _name = 'omni.binding.mixin'
    _inherit = ['omni.scope.mixin']
    _description = 'Channel Identity Binding'

    channel_id = fields.Many2one(
        'omni.channel', required=True, ondelete='restrict', check_company=True,
    )
    account_id = fields.Many2one(
        'omni.account', required=True, ondelete='restrict', check_company=True,
    )
    company_id = fields.Many2one(
        related='channel_id.company_id',
        store=True,
        readonly=True,
        precompute=True,
        default=None,
    )
    purpose_id = fields.Many2one(
        related='channel_id.purpose_id', store=True, readonly=True, precompute=True,
    )
    channel_type_id = fields.Many2one(
        related='channel_id.channel_type_id', store=True, required=True, precompute=True,
    )
    namespace = fields.Char(
        related='account_id.namespace', store=True, required=True, precompute=True,
    )
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    external_key = fields.Char(required=True)

    @api.constrains('channel_id', 'account_id', 'external_key')
    def _check_binding(self):
        for record in self:
            if (
                not record.external_key.strip()
                or record.external_key != record.external_key.strip()
            ):
                raise ValidationError(
                    _(
                        'An external identity must be non-empty and contain no surrounding spaces.',
                    ),
                )
            if (
                record.channel_id.channel_type_id != record.account_id.channel_type_id
                or record.purpose_id != record.account_id.purpose_id
                or record.company_id != record.account_id.company_id
            ):
                raise ValidationError(
                    _(
                        'Connection and channel must have the same company, purpose and channel type.',
                    ),
                )

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, {'company_id', 'purpose_id', 'channel_type_id', 'namespace'}, vals_list):
            raise AccessError(
                _('Ownership is derived from the selected channel and connection.'),
            )
        return super().create(vals_list)

    def write(self, vals):
        if {
            'channel_id',
            'account_id',
            'external_key',
            'company_id',
            'purpose_id',
            'channel_type_id',
            'namespace',
        } & vals.keys():
            raise UserError(
                _(
                    'Create a new configuration to change this identity. Existing ownership is immutable.',
                ),
            )
        return super().write(vals)


class OmniSender(models.Model):
    _name = 'omni.outbound.sender'
    _inherit = ['omni.binding.mixin']
    _description = 'Outbound Sender'

    is_selected = fields.Boolean(readonly=True, copy=False, string='Runtime sender')
    health = fields.Selection(
        [
            ('unknown', 'Not checked'),
            ('healthy', 'Healthy'),
            ('unhealthy', 'Unhealthy'),
        ],
        default='unknown',
        required=True,
        readonly=True,
        copy=False,
    )
    health_checked_at = fields.Datetime(readonly=True, copy=False)
    health_message = fields.Char(readonly=True, copy=False)
    _selected_unique = models.UniqueIndex(
        '(channel_id) WHERE is_selected', 'Only one runtime sender can be selected.',
    )
    _identity_unique = models.Constraint(
        'UNIQUE(channel_type_id, namespace, external_key)',
        'This sending identity is already owned by a channel.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, {'is_selected', 'health', 'health_checked_at', 'health_message'}, vals_list):
            raise AccessError(
                _(
                    'Sender selection and health can only be changed through verified actions.',
                ),
            )
        return super().create(vals_list)

    def write(self, vals):
        if {
            'is_selected',
            'health',
            'health_checked_at',
            'health_message',
        } & vals.keys():
            raise AccessError(
                _(
                    'Sender selection and health can only be changed through verified actions.',
                ),
            )
        for channel in self.channel_id.sorted('id'):
            channel._lock()
            channel._check_sender_change_allowed()
        self.invalidate_recordset()
        if 'active' in vals and not vals['active'] and self.filtered('is_selected'):
            raise UserError(_('Deactivate the runtime sender before archiving it.'))
        return super().write(vals)

    def unlink(self):
        for channel in self.channel_id.sorted('id'):
            channel._lock()
            channel._check_sender_change_allowed()
        self.invalidate_recordset()
        if self.filtered('is_selected'):
            raise UserError(_('Deactivate the runtime sender before removing it.'))
        return super().unlink()

    def _health_config(self):
        return {
            'account_key': self.account_id.external_account_key,
            'namespace': self.namespace,
            'sender_key': self.external_key,
            'credential_reference': self.account_id.credential_reference,
            'adapter': self.account_id._adapter_config(),
        }

    def _health_version(self):
        return (
            self.write_date, self.account_id.write_date, self.channel_id.write_date,
            self.active, self.account_id.active, self.channel_id.active,
        )

    def _check_health(self):
        self.ensure_one()
        self._require_manager()
        if not self.active or not self.account_id.active or not self.channel_id.active:
            raise UserError(
                _("Activate the channel, connection and sender configuration first."),
            )
        config, version = self._health_config(), self._health_version()
        started = time.monotonic()
        try:
            result = get_adapter(self.channel_type_id.code).check_sender_health(config)
            healthy = (
                result.healthy
                and result.namespace == self.namespace
                and result.account_key == config["account_key"]
                and result.sender_key == self.external_key
            )
            message = (
                _("Provider identity verified.")
                if healthy
                else _("The provider could not verify this sender identity.")
            )
        except AdapterUnavailable:
            healthy, message = (
                False,
                _("Install and configure the provider adapter before activation."),
            )
        except Exception:  # noqa: BLE001 - never persist provider errors or tokens
            healthy, message = (
                False,
                _(
                    "Provider verification failed. Review the connection and secret provisioning.",
                ),
            )
        # Only read-only preflight may happen above. Lock and recheck all inputs
        # before publishing health or selecting a sender. HTTP retry may repeat
        # this read-only request, but it must never send a message.
        self.channel_id._lock()
        self.invalidate_recordset()
        self.account_id.invalidate_recordset()
        if (
            config != self._health_config()
            or version != self._health_version()
            or time.monotonic() - started > 60
        ):
            raise UserError(
                _(
                    "Configuration changed or verification expired. Check the sender again.",
                ),
            )
        super().write(
            {
                "health": "healthy" if healthy else "unhealthy",
                "health_checked_at": fields.Datetime.now(),
                "health_message": message,
            },
        )
        self._audit("sender.health", message)
        return healthy

    def action_check_health(self):
        self._check_health()
        return True

    def action_activate(self, expected_generation):
        self.ensure_one()
        self._require_manager()
        channel = self.channel_id
        if channel.generation != expected_generation:
            raise UserError(
                _(
                    "The runtime sender changed while you were reviewing. Reopen the selection dialog.",
                ),
            )
        channel._check_sender_change_allowed()
        healthy = self._check_health()  # No selection lock during provider I/O.
        channel._check_sender_change_allowed()
        if channel.generation != expected_generation:
            raise UserError(
                _(
                    "The runtime sender changed while you were reviewing. Reopen the selection dialog.",
                ),
            )
        if not healthy:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sender not activated"),
                    "message": self.health_message,
                    "type": "warning",
                    "sticky": True,
                },
            }
        current = self.with_context(active_test=False).search(
            [("channel_id", "=", channel.id), ("is_selected", "=", True)],
        )
        if current == self:
            return True
        super(OmniSender, current).write({"is_selected": False})
        super().write({"is_selected": True})
        channel._advance_generation()
        self._audit(
            "sender.activated",
            _("Runtime sender selected after provider verification."),
        )
        return True

    def action_deactivate(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        self.channel_id._check_sender_change_allowed()
        self.invalidate_recordset()
        if self.is_selected:
            super().write({'is_selected': False})
            self.channel_id._advance_generation()
            self._audit('sender.deactivated', _('Outbound sending disabled.'))
        return True


class OmniEndpoint(models.Model):
    _name = 'omni.inbound.endpoint'
    _inherit = ['omni.binding.mixin']
    _description = 'Inbound Endpoint'

    state = fields.Selection(
        [('draft', 'Not enabled')],
        default='draft',
        readonly=True,
        help='Intake stays disabled until a verified adapter and an approved ingestion policy are available.',
    )
    _identity_unique = models.Constraint(
        'UNIQUE(channel_type_id, namespace, external_key)',
        'This physical endpoint is already owned by a channel, including archived configurations.',
    )


class OmniAudit(models.Model):
    _name = 'omni.audit.event'
    _inherit = ['omni.scope.mixin']
    _description = 'Communication Audit'
    _order = 'create_date desc, id desc'

    actor_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    event = fields.Char(required=True)
    resource = fields.Char(required=True)
    detail = fields.Text(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(
                _('Audit events are created only by verified server actions.'),
            )
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Audit events cannot be edited.'))

    def unlink(self):
        raise AccessError(_('Audit events cannot be deleted.'))


class OmniSenderSelection(models.TransientModel):
    _name = 'omni.sender.selection'
    _description = 'Select Runtime Sender'

    channel_id = fields.Many2one('omni.channel', required=True, readonly=True)
    sender_id = fields.Many2one(
        'omni.outbound.sender', required=True, string='Runtime sender',
    )
    expected_generation = fields.Integer(required=True, readonly=True)

    def action_confirm(self):
        self.ensure_one()
        self.check_access('read')
        if self.sender_id.channel_id != self.channel_id:
            raise UserError(_('Select a sender from this channel.'))
        result = self.sender_id.action_activate(self.expected_generation)
        return (
            result
            if isinstance(result, dict)
            else {'type': 'ir.actions.act_window_close'}
        )
