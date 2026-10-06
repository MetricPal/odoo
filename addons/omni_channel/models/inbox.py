"""Verified inbox, explicit processing policy, and supervised conversations."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import asdict
from datetime import timedelta

from psycopg2 import OperationalError

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .command import digest, internal, is_internal
from .deployment import channel_origin
from .dispatch import OmniDispatchCommand
from .foundation import protected_input
from odoo.addons.omni_channel.providers.base import get_adapter
from odoo.addons.omni_channel.providers.inbound import reject, verified_events


def lock_company(record):
    record.ensure_one()
    # A row-version change, not just SELECT FOR UPDATE, is required under Odoo's
    # REPEATABLE READ: a stale concurrent snapshot must serialize/retry before
    # it can miss a newly committed block or policy revocation. No business
    # value or write timestamp changes. This conservative boundary is per company.
    record.env.cr.execute(
        "UPDATE res_company SET write_date = write_date WHERE id = %s",
        [record.company_id.id],
    )


class InboxChannel(models.Model):
    _inherit = "omni.channel"

    def _lock(self):
        # Shared suppression boundary: company -> channel -> command/event.
        lock_company(self)
        return super()._lock()


class InboxOwned(models.AbstractModel):
    _name = "omni.inbox.owned"
    _inherit = "omni.scope.mixin"
    _description = "Server-owned inbox evidence"

    @api.model_create_multi
    def create(self, vals_list):
        if not is_internal(self):
            raise AccessError(
                _("Inbox evidence is created by verified processing only."),
            )
        return super().create(vals_list)

    def write(self, vals):
        if not is_internal(self):
            raise AccessError(_("Use the supervised inbox actions."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_("Inbox evidence is retained under its processing policy."))


class InboundPolicy(models.Model):
    _name = "omni.inbound.policy"
    _inherit = "omni.scope.mixin"
    _description = "Inbound Processing Policy"

    name = fields.Char(required=True)
    channel_id = fields.Many2one(
        "omni.channel", required=True, ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        related="channel_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="channel_id.purpose_id", store=True, precompute=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("paused", "Paused")],
        default="draft",
        required=True,
        readonly=True,
    )
    activated_by = fields.Many2one("res.users", readonly=True)
    activated_at = fields.Datetime(readonly=True)
    payload_days = fields.Integer(default=7, required=True)
    message_days = fields.Integer(default=90, required=True)
    blocked_days = fields.Integer(default=30, required=True)
    legal_hold = fields.Boolean(readonly=True)
    hash_key = fields.Char(
        default=lambda self: secrets.token_hex(32),
        readonly=True,
        groups="base.group_no_one",
        copy=False,
    )
    _active_unique = models.UniqueIndex(
        "(channel_id) WHERE state = 'active'",
        "One active processing policy per channel.",
    )
    _protected = {
        "company_id",
        "purpose_id",
        "state",
        "activated_by",
        "activated_at",
        "hash_key",
        "legal_hold",
    }

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._protected, vals_list):
            raise AccessError(
                _("Policy activation and retention controls require explicit actions."),
            )
        return super().create(vals_list)

    def write(self, vals):
        if self._protected & vals.keys() or any(p.state != "draft" for p in self):
            raise AccessError(
                _(
                    "Activated policy versions are immutable. Create a new policy to change retention.",
                ),
            )
        return super().write(vals)

    def unlink(self):
        if any(p.state != "draft" for p in self):
            raise AccessError(_("Activated policies are retained for audit."))
        return super().unlink()

    @api.constrains("payload_days", "message_days", "blocked_days")
    def _check_retention(self):
        for p in self:
            if not (
                1 <= p.payload_days <= 7
                and 1 <= p.message_days <= 365
                and 1 <= p.blocked_days <= 30
            ):
                raise ValidationError(
                    _(
                        "Retention must be 1–7 days for pending payloads, 1–365 for messages and 1–30 for blocked metadata.",
                    ),
                )

    def action_activate(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        try:
            ready = (
                get_adapter(self.channel_id.channel_type_id.code).inbound_release_ready
                is True
            )
        except Exception:  # noqa: BLE001 - fail closed without provider details
            ready = False
        if (
            not ready
            or not self.channel_id.active
            or self.state not in ("draft", "paused")
        ):
            raise UserError(
                _("A release-ready inbound adapter and active channel are required."),
            )
        super().write(
            {
                "state": "active",
                "activated_by": self.env.uid,
                "activated_at": fields.Datetime.now(),
            },
        )
        self._audit(
            "inbound.policy_activated",
            _(
                "Explicitly authorized text ingestion and the displayed retention periods. No contacts, business records or replies are authorized.",
            ),
        )
        return True

    def action_pause(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        super().write({"state": "paused"})
        self._audit(
            "inbound.policy_paused",
            _("Intake and normalization paused; approved retention remains in effect."),
        )
        return True

    def action_toggle_legal_hold(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        super().write({"legal_hold": not self.legal_hold})
        self._audit("inbound.legal_hold", _("Retention hold explicitly changed."))
        return True


class InboundEndpoint(models.Model):
    _inherit = "omni.inbound.endpoint"

    def _get_webhook_url(self):
        """Backend-only registration input; deriving a URL never registers it."""
        self.ensure_one()
        origin = channel_origin(self.get_base_url())
        return f"{origin}/omni/inbound/{self.route_key}" if origin else False

    state = fields.Selection(
        selection_add=[("enabled", "Enabled"), ("disabled", "Disabled")],
        ondelete={"enabled": "set default", "disabled": "set default"},
    )
    route_key = fields.Char(
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        groups="omni_channel.group_omni_manager",
    )
    ownership_version = fields.Integer(default=1, readonly=True)
    policy_id = fields.Many2one(
        "omni.inbound.policy", readonly=True, check_company=True, ondelete="restrict",
    )
    ingress_window = fields.Datetime(readonly=True)
    ingress_count = fields.Integer(readonly=True)
    _route_unique = models.Constraint(
        "UNIQUE(route_key)", "Inbound routes must be unique.",
    )
    _protected = {
        "state",
        "route_key",
        "ownership_version",
        "policy_id",
        "ingress_window",
        "ingress_count",
    }

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._protected, vals_list):
            raise AccessError(_("Use verified endpoint activation."))
        return super().create(vals_list)

    def write(self, vals):
        if self._protected & vals.keys() and not is_internal(self):
            raise AccessError(_("Endpoint intake state is server-managed."))
        for channel in self.channel_id.sorted("id"):
            channel._lock()
        return super().write(vals)

    def _config(self):
        self.ensure_one()
        return {
            "account_key": self.account_id.external_account_key,
            "namespace": self.namespace,
            "endpoint_key": self.external_key,
            "credential_reference": self.account_id.credential_reference or "",
            "adapter": self.account_id._adapter_config(),
        }

    def action_enable(self):
        self.ensure_one()
        self._require_manager()
        # Read-only bounded adapter check, outside the configuration lock.
        try:
            adapter = get_adapter(self.channel_type_id.code)
            config = self._config()
            valid = (
                adapter.inbound_release_ready is True
                and adapter.check_endpoint(config) is True
            )
        except Exception:  # noqa: BLE001
            valid = False
        self.channel_id._lock()
        self.invalidate_recordset()
        policy = self.env["omni.inbound.policy"].search(
            [("channel_id", "=", self.channel_id.id), ("state", "=", "active")], limit=1,
        )
        if (
            not valid
            or config != self._config()
            or not policy
            or not self.active
            or not self.account_id.active
            or not self.channel_id.active
        ):
            raise UserError(
                _(
                    "Verify the endpoint and activate a processing policy before enabling intake.",
                ),
            )
        internal(self).write({"state": "enabled", "policy_id": policy.id})
        self._audit(
            "inbound.enabled",
            _("Verified intake enabled under the selected processing policy."),
        )
        return True

    def action_disable(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        internal(self).write({"state": "disabled"})
        self._audit(
            "inbound.disabled", _("New intake and queued normalization disabled."),
        )
        return True

    def _allowed(self, policy=None):
        self.ensure_one()
        policy = policy or self.policy_id
        return (
            self.state == "enabled"
            and self.active
            and self.account_id.active
            and self.channel_id.active
            and policy == self.policy_id
            # Policy records remain administrator-only. Read just the internal
            # activation flag after validating the endpoint/policy binding.
            and policy.sudo().state == "active"
        )

    def _receive(self, raw, headers):
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_("Only verified transport may receive events."))
        if not self._allowed():
            reject("disabled")
        events, raw_hash = verified_events(
            self.channel_type_id.code, raw, headers, self._config(),
        )
        self.channel_id._lock()
        self.invalidate_recordset()
        if not self._allowed():
            reject("disabled")
        now = fields.Datetime.now()
        count = (
            self.ingress_count
            if self.ingress_window and self.ingress_window > now - timedelta(minutes=1)
            else 0
        )
        if count + len(events) > 600:
            reject("rate")
        internal(self).write(
            {
                "ingress_count": count + len(events),
                "ingress_window": self.ingress_window if count else now,
            },
        )
        for event in events:
            self.env["omni.webhook.event"]._store(self, event, raw_hash)
        return True


class BlockedIdentity(models.Model):
    _name = "omni.blocked.identity"
    _inherit = "omni.scope.mixin"
    _description = "Blocked Communication Identity"

    purpose_id = fields.Many2one("omni.purpose", required=False, ondelete="restrict")
    channel_type_id = fields.Many2one(
        "omni.channel.type", required=True, ondelete="restrict",
    )
    namespace = fields.Char(required=True)
    external_key = fields.Char(required=True, string="Identity key")
    reason = fields.Text(required=True)
    expires_at = fields.Datetime()
    state = fields.Selection(
        [("draft", "Draft"), ("blocked", "Blocked"), ("revoked", "Unblocked")],
        default="draft",
        readonly=True,
        required=True,
    )
    actor_id = fields.Many2one("res.users", readonly=True)
    blocked_at = fields.Datetime(readonly=True)
    unblocked_by = fields.Many2one("res.users", readonly=True)
    unblocked_at = fields.Datetime(readonly=True)
    _purpose_unique = models.UniqueIndex(
        "(company_id, purpose_id, channel_type_id, namespace, external_key) WHERE state = 'blocked' AND purpose_id IS NOT NULL",
        "This identity is already blocked for this team.",
    )
    _company_unique = models.UniqueIndex(
        "(company_id, channel_type_id, namespace, external_key) WHERE state = 'blocked' AND purpose_id IS NULL",
        "This identity is already blocked company-wide.",
    )
    _protected = {"state", "actor_id", "blocked_at", "unblocked_by", "unblocked_at"}

    @api.constrains("purpose_id", "company_id")
    def _check_scope(self):
        for row in self:
            if not self.env.su and (
                row.company_id not in self.env.companies
                or (row.purpose_id and self.env.user not in row.purpose_id.user_ids)
            ):
                raise AccessError(_("This suppression scope is not available to you."))

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._protected, vals_list):
            raise AccessError(_("Blocking requires explicit confirmation."))
        return super().create(vals_list)

    def write(self, vals):
        if self._protected & vals.keys() or any(row.state != "draft" for row in self):
            raise AccessError(_("Confirmed blocks are immutable. Use Unblock."))
        return super().write(vals)

    def unlink(self):
        if any(row.state != "draft" for row in self):
            raise AccessError(_("Block decisions are retained for audit."))
        return super().unlink()

    def _authorize(self):
        self.ensure_one()
        self.check_access("write")
        if not self.purpose_id and not self.env.user.has_group("base.group_system"):
            raise AccessError(
                _("Company-wide blocking requires a system administrator."),
            )
        lock_company(self)
        self.invalidate_recordset()

    def action_block(self):
        self._authorize()
        if (
            self.state != "draft"
            or not self.reason.strip()
            or any(
                not s.strip() or s != s.strip()
                for s in (self.namespace, self.external_key)
            )
        ):
            raise UserError(_("Confirm a draft with an exact identity and a reason."))
        if self.expires_at and self.expires_at <= fields.Datetime.now():
            raise UserError(_("Block expiry must be in the future."))
        super().write(
            {
                "state": "blocked",
                "actor_id": self.env.uid,
                "blocked_at": fields.Datetime.now(),
            },
        )
        # Purge pending content immediately; blocked events never become replayable.
        pending = (
            self.env["omni.webhook.event"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("state", "in", ["received", "retry", "dead", "unresolved"]),
                    ("endpoint_id.channel_type_id", "=", self.channel_type_id.id),
                    ("endpoint_id.namespace", "=", self.namespace),
                ]
                + ([("purpose_id", "=", self.purpose_id.id)] if self.purpose_id else []),
            )
        )
        for event in pending:
            if event.identity_hash == event._identity_hash(self.external_key):
                event._suppress()
        # Company-wide audit has no purpose: record one scoped event per affected team.
        channels = (
            self.env["omni.channel"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("channel_type_id", "=", self.channel_type_id.id),
                ]
                + ([("purpose_id", "=", self.purpose_id.id)] if self.purpose_id else []),
            )
        )
        for channel in channels:
            channel.with_user(self.env.user)._audit(
                "identity.blocked",
                _(
                    "Confirmed suppression; pending content removed and future claims prevented.",
                ),
            )
        return True

    def action_unblock(self):
        self._authorize()
        if self.state != "blocked":
            raise UserError(_("Only an active block can be removed."))
        super().write(
            {
                "state": "revoked",
                "unblocked_by": self.env.uid,
                "unblocked_at": fields.Datetime.now(),
            },
        )
        channels = (
            self.env["omni.channel"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("channel_type_id", "=", self.channel_type_id.id),
                ]
                + ([("purpose_id", "=", self.purpose_id.id)] if self.purpose_id else []),
            )
        )
        for channel in channels:
            channel.with_user(self.env.user)._audit(
                "identity.unblocked",
                _("Confirmed unblock; no replay and no recipient consent granted."),
            )
        # Deliberately no replay and no grant of recipient consent.
        return True

    @api.model
    def _matches(self, channel, namespace, key):
        return bool(
            self.sudo().search_count(
                [
                    ("company_id", "=", channel.company_id.id),
                    ("channel_type_id", "=", channel.channel_type_id.id),
                    ("namespace", "=", namespace),
                    ("external_key", "=", key),
                    ("state", "=", "blocked"),
                    "|",
                    ("purpose_id", "=", False),
                    ("purpose_id", "=", channel.purpose_id.id),
                    "|",
                    ("expires_at", "=", False),
                    ("expires_at", ">", fields.Datetime.now()),
                ],
            ),
        )


class InboxIdentity(models.Model):
    _name = "omni.identity"
    _inherit = "omni.inbox.owned"
    _description = "Communication Identity"
    _rec_name = "external_key"

    channel_id = fields.Many2one(
        "omni.channel", required=True, ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        related="channel_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="channel_id.purpose_id", store=True, precompute=True,
    )
    namespace = fields.Char(required=True)
    external_key = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', readonly=True, check_company=True, ondelete='restrict', groups='base.group_no_one')

    def _visible_partner(self):
        self.ensure_one()
        self.check_access('read')
        partner = self.sudo().partner_id.with_user(self.env.user)
        if partner and partner.has_access('read') and (not partner.company_id or partner.company_id == self.company_id):
            return partner
        return self.env['res.partner']

    _identity_unique = models.Constraint(
        "UNIQUE(channel_id, namespace, external_key)",
        "Identity already exists in this team.",
    )


class InboxConversation(models.Model):
    _name = "omni.conversation"
    _inherit = "omni.inbox.owned"
    _description = "Supervised Inbox"
    _order = "last_message_at desc, id desc"
    _rec_name = "thread_key"

    channel_id = fields.Many2one(
        "omni.channel", required=True, ondelete="restrict", check_company=True,
    )
    endpoint_id = fields.Many2one(
        "omni.inbound.endpoint", required=True, ondelete="restrict", check_company=True,
    )
    ownership_version = fields.Integer(required=True)
    company_id = fields.Many2one(
        related="channel_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="channel_id.purpose_id", store=True, precompute=True,
    )
    identity_id = fields.Many2one(
        "omni.identity", required=True, ondelete="restrict", check_company=True,
    )
    thread_key = fields.Char(required=True)
    state = fields.Selection(
        [
            ("new", "New"),
            ("open", "Open"),
            ("waiting", "Waiting"),
            ("closed", "Closed"),
        ],
        default="new",
        required=True,
        readonly=True,
    )
    assigned_user_id = fields.Many2one("res.users", readonly=True)
    last_message_at = fields.Datetime(index=True)
    message_ids = fields.One2many("omni.message", "conversation_id", readonly=True)
    command_ids = fields.One2many("omni.command", "conversation_id", readonly=True)
    reply_blocked_reason = fields.Char(compute="_compute_reply_blocked")
    _thread_unique = models.Constraint(
        "UNIQUE(endpoint_id, ownership_version, thread_key)",
        "Conversation already exists.",
    )

    contact_name = fields.Char(compute='_compute_contact_name', string='Linked contact')

    @api.depends('identity_id.partner_id', 'identity_id.partner_id.display_name', 'identity_id.partner_id.company_id')
    @api.depends_context('uid', 'company')
    def _compute_contact_name(self):
        for conversation in self:
            partner = conversation.identity_id._visible_partner()
            conversation.contact_name = partner.display_name if partner else False

    def action_link_contact(self):
        self.ensure_one()
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'res_model': 'omni.contact.link', 'view_mode': 'form', 'target': 'new',
                'context': {'default_identity_id': self.identity_id.id}}

    def action_open_contact(self):
        self.ensure_one()
        self.check_access('read')
        partner = self.identity_id._visible_partner()
        if not partner:
            raise AccessError(_('No linked contact is available with your current permissions.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'res.partner', 'res_id': partner.id, 'view_mode': 'form', 'target': 'current'}

    def _reply_check(self):
        self.ensure_one()
        self.check_access("read")
        endpoint = self.endpoint_id
        sender = self.channel_id.selected_sender_id
        if self.env["omni.blocked.identity"]._matches(
            self.channel_id, endpoint.namespace, self.identity_id.external_key,
        ):
            return _("This identity is blocked. Unblocking does not grant consent.")
        if (
            not sender
            or sender.health != "healthy"
            or not sender.active
            or not sender.account_id.active
            or sender.account_id != endpoint.account_id
            or sender.namespace != endpoint.namespace
            or not self.channel_id.active
            or self.ownership_version != endpoint.ownership_version
        ):
            return _(
                "Select a healthy sender on the original connection before replying. No alternate sender is used.",
            )
        if not self.message_ids.filtered(lambda m: not m.redacted):
            return _(
                "The message content has expired. Review fresh context before preparing a reply.",
            )
        return False

    @api.depends("channel_id.selected_sender_id", "identity_id")
    def _compute_reply_blocked(self):
        for row in self:
            row.reply_blocked_reason = row._reply_check()

    def action_assign_me(self):
        self.ensure_one()
        self.check_access("write")
        if self.env.user.share or not self.env.user.active:
            raise AccessError(
                _("Only active internal operators can own conversations."),
            )
        self.channel_id._lock()
        internal(self).write({"assigned_user_id": self.env.uid, "state": "open"})
        self._audit("conversation.assigned", _("Operator explicitly took ownership."))
        return True

    def action_set_state(self, state):
        self.ensure_one()
        self.check_access("write")
        if state not in ("open", "waiting", "closed"):
            raise UserError(_("Choose an available conversation state."))
        self.channel_id._lock()
        internal(self).write({"state": state})
        self._audit(
            "conversation.state",
            _("Conversation status explicitly changed. No message sent."),
        )
        return True

    def action_close(self):
        return self.action_set_state("closed")

    def action_wait(self):
        return self.action_set_state("waiting")

    def action_reopen(self):
        return self.action_set_state("open")

    def action_prepare_reply(self):
        self.ensure_one()
        self.check_access("write")
        self.channel_id._lock()
        reason = self._reply_check()
        if reason:
            raise UserError(reason)
        command = internal(self.env["omni.command"]).create(
            {
                "name": _("Reply to %s", self.thread_key),
                "channel_id": self.channel_id.id,
                "conversation_id": self.id,
                "recipient": self.identity_id.external_key,
                "body": "",
                "reason": _("Reply to the verified private conversation."),
            },
        )
        self._audit(
            "conversation.reply_prepared",
            _("Draft prepared for human editing and separate approval."),
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "omni.command",
            "res_id": command.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_block(self):
        self.ensure_one()
        self.check_access("write")
        return {
            "type": "ir.actions.act_window",
            "res_model": "omni.blocked.identity",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_company_id": self.company_id.id,
                "default_purpose_id": self.purpose_id.id,
                "default_channel_type_id": self.channel_id.channel_type_id.id,
                "default_namespace": self.identity_id.namespace,
                "default_external_key": self.identity_id.external_key,
            },
        }


class InboxMessage(models.Model):
    _name = "omni.message"
    _inherit = "omni.inbox.owned"
    _description = "Verified Inbound Message"
    _order = "occurred_at, id"

    conversation_id = fields.Many2one(
        "omni.conversation", required=True, ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        related="conversation_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="conversation_id.purpose_id", store=True, precompute=True,
    )
    policy_id = fields.Many2one(
        "omni.inbound.policy", required=True, ondelete="restrict", check_company=True,
    )
    external_key = fields.Char(required=True)
    body = fields.Text(readonly=True)
    occurred_at = fields.Datetime(required=True)
    revision = fields.Integer(default=0, readonly=True)
    revision_ids = fields.One2many(
        "omni.message.revision", "message_id", readonly=True, string="Revision history",
    )
    redacted = fields.Boolean(readonly=True)
    expires_at = fields.Datetime(required=True, index=True)
    _message_unique = models.Constraint(
        "UNIQUE(conversation_id, external_key)", "Message already exists.",
    )


class MessageRevision(models.Model):
    _name = "omni.message.revision"
    _inherit = "omni.inbox.owned"
    _description = "Inbound Message Revision"
    _order = "revision"

    message_id = fields.Many2one(
        "omni.message", required=True, ondelete="restrict", check_company=True,
    )
    event_id = fields.Many2one(
        "omni.webhook.event", required=True, ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        related="message_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="message_id.purpose_id", store=True, precompute=True,
    )
    revision = fields.Integer(required=True)
    body = fields.Text(readonly=True)
    content_hash = fields.Char(required=True)
    _revision_unique = models.Constraint(
        "UNIQUE(message_id, revision)", "Message revision already exists.",
    )


class WebhookEvent(models.Model):
    _name = "omni.webhook.event"
    _inherit = "omni.inbox.owned"
    _description = "Verified Intake Event"
    _order = "id desc"
    _rec_name = "event_hash"

    endpoint_id = fields.Many2one(
        "omni.inbound.endpoint", required=True, ondelete="restrict", check_company=True,
    )
    account_id = fields.Many2one(related="endpoint_id.account_id", store=True, precompute=True, required=True)
    company_id = fields.Many2one(
        related="endpoint_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="endpoint_id.purpose_id", store=True, precompute=True,
    )
    policy_id = fields.Many2one(
        "omni.inbound.policy", required=True, ondelete="restrict", check_company=True,
    )
    ownership_version = fields.Integer(required=True)
    event_hash = fields.Char(required=True)
    identity_hash = fields.Char(index=True)
    payload_hash = fields.Char(required=True)
    raw_hash = fields.Char(required=True)
    payload = fields.Json(groups="omni_channel.group_omni_manager")
    kind = fields.Char(required=True)
    state = fields.Selection(
        [
            (s, label)
            for s, label in [
                ("received", "Received"),
                ("processed", "Processed"),
                ("blocked", "Blocked"),
                ("unresolved", "Needs review"),
                ("retry", "Retry scheduled"),
                ("dead", "Dead letter"),
                ("expired", "Content expired"),
                ("ignored", "Unsupported"),
            ]
        ],
        default="received",
        readonly=True,
        required=True,
        index=True,
    )
    reason_code = fields.Char(readonly=True)
    attempts = fields.Integer(readonly=True)
    next_attempt_at = fields.Datetime(readonly=True)
    expires_at = fields.Datetime(required=True, index=True)
    message_id = fields.Many2one(
        "omni.message", readonly=True, ondelete="restrict", check_company=True,
    )
    collision = fields.Boolean(readonly=True)
    _event_unique = models.Constraint(
        "UNIQUE(account_id, event_hash)", "Event already received.",
    )
    _due_index = models.Index("(state, next_attempt_at, id)")

    def _identity_hash(self, key):
        return hmac.new(
            self.policy_id.sudo().hash_key.encode(), key.encode(), hashlib.sha256,
        ).hexdigest()

    @api.model
    def _store(self, endpoint, event, raw_hash):
        policy = endpoint.policy_id
        # Stable per-account event hash survives policy changes; blocked identities use a keyed hash.
        event_hash = hashlib.sha256(event.event_key.encode()).hexdigest()
        payload = asdict(event)
        fingerprint = digest(payload)
        existing = self.search(
            [
                ("account_id", "=", endpoint.account_id.id),
                ("event_hash", "=", event_hash),
            ],
            limit=1,
        )
        if existing:
            if existing.state == "expired":
                return existing  # Content was deliberately erased; keep the dedup tombstone.
            if existing.payload_hash != fingerprint:
                internal(existing).write(
                    {
                        "collision": True,
                        "reason_code": "event_key_collision",
                        "payload": existing.payload
                        if existing.policy_id.legal_hold
                        else False,
                        "state": "unresolved"
                        if existing.state not in ("blocked", "expired")
                        else existing.state,
                    },
                )
                existing._audit(
                    "inbound.collision",
                    _(
                        "Reused event key with changed content. Original normalized history was preserved.",
                    ),
                )
            return existing
        identity_hash = hmac.new(
            policy.sudo().hash_key.encode(), event.sender_key.encode(), hashlib.sha256,
        ).hexdigest()
        state, reason = "received", False
        if (
            event.endpoint_key != endpoint.external_key
            or event.namespace != endpoint.namespace
        ):
            state, reason = "unresolved", "endpoint_mismatch"
        elif event.kind == "receipt":
            state, reason = "unresolved", "receipt_reconciliation_pending"
        elif event.kind == "unsupported" or not event.private:
            state, reason = "ignored", "unsupported_event"
        elif self.env["omni.blocked.identity"]._matches(
            endpoint.channel_id, endpoint.namespace, event.sender_key,
        ):
            state, reason = "blocked", "identity_blocked"
        return internal(self).create(
            {
                "endpoint_id": endpoint.id,
                "policy_id": policy.id,
                "ownership_version": endpoint.ownership_version,
                "event_hash": event_hash,
                "identity_hash": identity_hash,
                "payload_hash": fingerprint,
                "raw_hash": raw_hash,
                "kind": event.kind,
                "state": state,
                "reason_code": reason,
                "payload": payload if state == "received" else False,
                "expires_at": fields.Datetime.now()
                + timedelta(
                    days=policy.blocked_days
                    if state == "blocked"
                    else policy.payload_days,
                ),
            },
        )

    def _suppress(self):
        # A hold preserves previously accepted restricted evidence, never new
        # blocked input. It still cannot normalize or replay while suppressed.
        internal(self).write(
            {
                "state": "blocked",
                "payload": self.payload if self.policy_id.legal_hold else False,
                "reason_code": "identity_blocked",
                "expires_at": fields.Datetime.now()
                + timedelta(days=self.policy_id.blocked_days),
            },
        )

    def _process_one(self):
        self.ensure_one()
        endpoint = self.endpoint_id
        endpoint.channel_id._lock()
        self.invalidate_recordset()
        if self.state not in ("received", "retry"):
            return
        if self.expires_at <= fields.Datetime.now():
            internal(self).write(
                {
                    "state": "unresolved" if self.policy_id.legal_hold else "expired",
                    "payload": self.payload if self.policy_id.legal_hold else False,
                    "reason_code": "content_expired",
                },
            )
            return
        if (
            not endpoint._allowed(self.policy_id)
            or endpoint.ownership_version != self.ownership_version
        ):
            internal(self).write(
                {"state": "unresolved", "reason_code": "policy_or_ownership_changed"},
            )
            return
        payload = self.payload
        if not payload or self.collision:
            internal(self).write(
                {"state": "unresolved", "reason_code": "payload_unavailable"},
            )
            return
        if self.env["omni.blocked.identity"]._matches(
            endpoint.channel_id, endpoint.namespace, payload["sender_key"],
        ):
            self._suppress()
            return
        identity_model = internal(self.env["omni.identity"])
        identity = identity_model.search(
            [
                ("channel_id", "=", endpoint.channel_id.id),
                ("namespace", "=", endpoint.namespace),
                ("external_key", "=", payload["sender_key"]),
            ],
            limit=1,
        )
        conversation_model = internal(self.env["omni.conversation"])
        conversation = conversation_model.search(
            [
                ("endpoint_id", "=", endpoint.id),
                ("ownership_version", "=", self.ownership_version),
                ("thread_key", "=", payload["thread_key"]),
            ],
            limit=1,
        )
        if conversation and conversation.identity_id != identity:
            internal(self).write(
                {
                    "state": "unresolved",
                    "payload": self.payload if self.policy_id.legal_hold else False,
                    "reason_code": "private_identity_mismatch",
                },
            )
            return
        if not identity:
            identity = identity_model.create(
                {
                    "channel_id": endpoint.channel_id.id,
                    "namespace": endpoint.namespace,
                    "external_key": payload["sender_key"],
                },
            )
        if not conversation:
            conversation = conversation_model.create(
                {
                    "channel_id": endpoint.channel_id.id,
                    "endpoint_id": endpoint.id,
                    "ownership_version": self.ownership_version,
                    "identity_id": identity.id,
                    "thread_key": payload["thread_key"],
                },
            )
        message_model = internal(self.env["omni.message"])
        message = message_model.search(
            [
                ("conversation_id", "=", conversation.id),
                ("external_key", "=", payload["message_key"]),
            ],
            limit=1,
        )
        if not message:
            message = message_model.create(
                {
                    "conversation_id": conversation.id,
                    "policy_id": self.policy_id.id,
                    "external_key": payload["message_key"],
                    "body": payload["body"],
                    "occurred_at": payload["occurred_at"],
                    "revision": payload["revision"],
                    "expires_at": self.create_date
                    + timedelta(days=self.policy_id.message_days),
                },
            )
        revision_model = internal(self.env["omni.message.revision"])
        revision = revision_model.search(
            [("message_id", "=", message.id), ("revision", "=", payload["revision"])],
            limit=1,
        )
        if revision and revision.content_hash != digest(payload["body"]):
            internal(self).write(
                {
                    "state": "unresolved",
                    "payload": self.payload if self.policy_id.legal_hold else False,
                    "collision": True,
                    "reason_code": "revision_collision",
                },
            )
            return
        if not revision and not message.redacted:
            revision_model.create(
                {
                    "message_id": message.id,
                    "event_id": self.id,
                    "revision": payload["revision"],
                    "body": payload["body"],
                    "content_hash": digest(payload["body"]),
                },
            )
            if payload["revision"] >= message.revision:
                internal(message).write(
                    {"body": payload["body"], "revision": payload["revision"]},
                )
        occurred = fields.Datetime.to_datetime(payload["occurred_at"])
        if not conversation.last_message_at or occurred > conversation.last_message_at:
            internal(conversation).write(
                {
                    "last_message_at": occurred,
                    "state": "open"
                    if conversation.state == "closed"
                    else conversation.state,
                },
            )
        internal(self).write(
            {
                "state": "processed",
                "payload": False,
                "message_id": message.id,
                "reason_code": False,
            },
        )
        self._audit(
            "inbound.processed",
            _(
                "Verified private text normalized without business-record or outbound effects.",
            ),
        )

    @api.model
    def _process_batch(self, limit=50):
        if not self.env.su:
            raise AccessError(_("Only the private inbox worker may normalize events."))
        due = self.search(
            [
                ("state", "in", ["received", "retry"]),
                "|",
                ("next_attempt_at", "=", False),
                ("next_attempt_at", "<=", fields.Datetime.now()),
            ],
            order="id",
            limit=min(max(int(limit), 1), 100),
        )
        for event in due:
            event.endpoint_id.channel_id._lock()
            event.invalidate_recordset()
            if event.state not in ("received", "retry"):
                continue
            attempt = event.attempts + 1
            try:
                with self.env.cr.savepoint():
                    event._process_one()
            except OperationalError:
                raise  # Let the framework retry database serialization/deadlocks.
            except Exception:  # noqa: BLE001 - rollback business effects, retain safe retry evidence
                internal(event).write(
                    {
                        "state": "dead" if attempt >= 5 else "retry",
                        "reason_code": "normalization_failed",
                        "next_attempt_at": fields.Datetime.now()
                        + timedelta(seconds=min(900, 5 * 2 ** (attempt - 1))),
                    },
                )
            internal(event).write({"attempts": attempt})
        return len(due)

    @api.model
    def _cron_process(self):
        if not self.env.su:
            raise AccessError(_("Only the system inbox worker may run."))
        with self.env.registry.cursor() as cr:
            api.Environment(cr, SUPERUSER_ID, {})["omni.webhook.event"]._process_batch()
            cr.commit()

    def action_replay(self):
        self.ensure_one()
        self._require_manager()
        self.endpoint_id.channel_id._lock()
        self.invalidate_recordset()
        if (
            self.state not in ("dead", "unresolved")
            or not self.payload
            or self.collision
            or self.expires_at <= fields.Datetime.now()
        ):
            raise UserError(
                _(
                    "Only recoverable retained events can be replayed. Blocked or expired content cannot be restored.",
                ),
            )
        if (
            not self.endpoint_id._allowed(self.policy_id)
            or self.ownership_version != self.endpoint_id.ownership_version
        ):
            raise UserError(
                _("Restore the original endpoint and processing policy before replay."),
            )
        if self.env["omni.blocked.identity"]._matches(
            self.endpoint_id.channel_id,
            self.endpoint_id.namespace,
            self.payload["sender_key"],
        ):
            self._suppress()
            return True
        internal(self).write(
            {"state": "received", "next_attempt_at": False, "attempts": 0},
        )
        self._audit(
            "inbound.replayed",
            _("Operator requested normalization using the original event key."),
        )
        return True

    @api.model
    def _cron_retention(self, limit=100):
        if not self.env.su:
            raise AccessError(_("Only the policy-bound retention worker may purge."))
        now = fields.Datetime.now()
        policies = self.env["omni.inbound.policy"].search(
            [("activated_at", "!=", False), ("legal_hold", "=", False)],
        )
        for policy in policies:
            policy.channel_id._lock()
            policy.invalidate_recordset()
            if policy.legal_hold:
                continue
            events = self.search(
                [
                    ("policy_id", "=", policy.id),
                    ("expires_at", "<=", now),
                    ("raw_hash", "!=", "expired"),
                ],
                limit=limit,
            )
            for event in events:
                internal(event).write(
                    {
                        "payload": False,
                        "identity_hash": False,
                        "raw_hash": "expired",
                        "payload_hash": "expired",
                        "state": "expired",
                        "reason_code": "retention",
                    },
                )
            messages = self.env["omni.message"].search(
                [
                    ("policy_id", "=", policy.id),
                    ("expires_at", "<=", now),
                    ("redacted", "=", False),
                ],
                limit=limit,
            )
            for message in messages:
                internal(message.revision_ids).write({"body": False})
                internal(message).write({"body": False, "redacted": True})
            if events or messages:
                policy._audit(
                    "inbound.retention",
                    _(
                        "Expired payload and message content removed under the activated policy.",
                    ),
                )


class InboxCommand(models.Model):
    _inherit = "omni.command"

    conversation_id = fields.Many2one(
        "omni.conversation", readonly=True, ondelete="restrict", check_company=True,
    )
    _protected = OmniDispatchCommand._protected | {"conversation_id"}

    def copy(self, default=None):
        # Validate caller overrides through the existing guarded create path;
        # only then carry the original conversation into the fresh draft.
        command = super().copy(default)
        if self.conversation_id:
            internal(command).write({"conversation_id": self.conversation_id.id})
        return command

    def _extra_payload(self):
        values = super()._extra_payload()
        if self.conversation_id:
            conversation = self.conversation_id
            values["conversation"] = {
                "id": conversation.id,
                "endpoint": conversation.endpoint_id.external_key,
                "namespace": conversation.endpoint_id.namespace,
                "ownership_version": conversation.ownership_version,
                "thread": conversation.thread_key,
                "identity": conversation.identity_id.external_key,
            }
        return values

    def _check_conversation(self):
        self.ensure_one()
        if self.conversation_id:
            conversation = self.conversation_id.with_user(self.requester_id)
            conversation.check_access("read")
            reason = conversation._reply_check()
            if (
                reason
                or conversation.channel_id != self.channel_id
                or conversation.identity_id.external_key != self.recipient
            ):
                raise UserError(
                    reason
                    or _("The reply no longer matches the verified conversation."),
                )

    def action_submit(self):
        self.ensure_one()
        self._lock()
        self._check_conversation()
        sender = self.channel_id.selected_sender_id
        if sender and self.env["omni.blocked.identity"]._matches(
            self.channel_id, sender.namespace, self.recipient,
        ):
            raise UserError(_("This recipient is blocked."))
        return super().action_submit()

    def _check_dispatch_authorization(self):
        super()._check_dispatch_authorization()
        self._check_conversation()
        if self.env["omni.blocked.identity"]._matches(
            self.channel_id, self.sender_id.namespace, self.recipient,
        ):
            raise AccessError(_("Current recipient suppression prevents dispatch."))


class InboxContactLink(models.TransientModel):
    _name = 'omni.contact.link'
    _description = 'Confirm Existing Contact Link'

    identity_id = fields.Many2one('omni.identity', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', required=True, string='Existing contact')

    def action_confirm(self):
        self.ensure_one()
        self.check_access('read')
        identity = self.identity_id
        identity.check_access('read')
        if not self.env.user.has_group('omni_channel.group_omni_user') or self.env.user.share:
            raise AccessError(_('Only an authorized internal operator can link contacts.'))
        self.partner_id.check_access('read')
        if self.partner_id.company_id and self.partner_id.company_id != identity.company_id:
            raise UserError(_('Choose a contact belonging to this company or a permitted shared contact.'))
        identity.channel_id._lock()
        internal(identity.sudo()).write({'partner_id': self.partner_id.id})
        identity._audit('identity.contact_linked', _('Operator explicitly linked an existing accessible contact. No contact was created or merged.'))
        return {'type': 'ir.actions.act_window_close'}
