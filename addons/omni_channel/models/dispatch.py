"""PostgreSQL outbox and a disabled-by-default cron orchestrator."""

import json
import random
import time
import uuid
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .command import OmniCommand, internal, is_internal
from .foundation import OmniSender, protected_input
from odoo.addons.omni_channel.providers.dispatch import (
    DispatchClaim,
    dispatch_claim,
    normalize_result,
)


class OmniDispatchChannel(models.Model):
    _inherit = "omni.channel"

    dispatch_enabled = fields.Boolean(default=False, readonly=True, copy=False)
    dispatch_interval_seconds = fields.Integer(default=1, required=True)
    next_dispatch_at = fields.Datetime(readonly=True, copy=False, index=True)
    circuit_until = fields.Datetime(readonly=True, copy=False)
    failure_count = fields.Integer(readonly=True, copy=False)
    failure_window_start = fields.Datetime(readonly=True, copy=False)
    _worker_fields = {
        "dispatch_enabled",
        "next_dispatch_at",
        "circuit_until",
        "failure_count",
        "failure_window_start",
    }

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._worker_fields, vals_list) and not is_internal(
            self,
        ):
            raise AccessError(_("Worker controls cannot be initialized by a client."))
        return super().create(vals_list)

    def write(self, vals):
        if self._worker_fields & vals.keys() and not is_internal(self):
            raise AccessError(
                _("Use the dispatch controls; internal worker fields are protected."),
            )
        if not is_internal(self):
            for channel in self.sorted("id"):
                channel._lock()
        return super().write(vals)

    @api.constrains("dispatch_interval_seconds")
    def _check_dispatch_interval(self):
        if any(not 1 <= channel.dispatch_interval_seconds <= 3600 for channel in self):
            raise ValidationError(
                _("The dispatch interval must be between 1 and 3600 seconds."),
            )

    def _check_sender_change_allowed(self):
        self.ensure_one()
        if (
            self.env["omni.command"]
            .sudo()
            .search_count(
                [
                    ("channel_id", "=", self.id),
                    ("state", "in", ["dispatching", "unknown"]),
                ],
            )
        ):
            raise UserError(
                _(
                    "Resolve in-flight or unknown outcomes before changing the runtime sender.",
                ),
            )

    def action_pause_dispatch(self):
        self.ensure_one()
        self._require_manager()
        self._lock()
        internal(self).write({"dispatch_enabled": False})
        self._audit(
            "dispatch.paused",
            _("New dispatch claims paused. In-flight requests may still complete."),
        )
        return True


class OmniConsent(models.Model):
    _name = "omni.consent"
    _inherit = ["omni.scope.mixin"]
    _description = "Recipient Authorization Evidence"
    _order = "create_date desc, id desc"

    channel_id = fields.Many2one(
        "omni.channel", required=True, check_company=True, ondelete="restrict",
        help="Choose the channel whose company and communication purpose this authorization covers.",
    )
    company_id = fields.Many2one(
        related="channel_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="channel_id.purpose_id", store=True, precompute=True,
    )
    namespace = fields.Char(
        required=True, string="Provider account namespace",
        help="Copy the Namespace from the provider connection used by this channel's runtime sender. It must match exactly; do not enter a bot token or password.",
    )
    recipient = fields.Char(
        required=True, string="Recipient identifier",
        help="Enter the exact destination identifier used by the provider. For Telegram, use the numeric chat ID from the verified conversation, not a contact name, phone number or @username. This field does not look up or verify the recipient.",
    )
    evidence = fields.Text(
        required=True,
        string="Authorization evidence",
        help="Describe who authorized contact, when and where they did so, and which messages are covered. Include a reference to the request or agreement. This note is reviewed by a person; the system does not verify it automatically.",
    )
    expires_at = fields.Datetime(
        required=True, default=lambda self: fields.Datetime.now() + timedelta(days=30),
        help="Sending requires authorization that has not expired. The default is 30 days; choose a date consistent with the evidence. Expired records may still show Confirmed, but cannot authorize a send.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("revoked", "Revoked")],
        default="draft",
        required=True,
        readonly=True,
    )
    confirmed_by = fields.Many2one("res.users", readonly=True)
    confirmed_at = fields.Datetime(readonly=True)
    _protected = {"state", "confirmed_by", "confirmed_at", "company_id", "purpose_id"}
    _scope_unique = models.UniqueIndex(
        "(channel_id, namespace, recipient) WHERE state = 'confirmed'",
        "Confirmed recipient evidence already exists for this scope.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if protected_input(self, self._protected, vals_list):
            raise AccessError(
                _("Use the explicit confirmation action to authorize a recipient."),
            )
        return super().create(vals_list)

    def write(self, vals):
        if self._protected & vals.keys() or any(item.state != "draft" for item in self):
            raise AccessError(
                _(
                    "Confirmed evidence is immutable. Revoke it if authorization is withdrawn.",
                ),
            )
        return super().write(vals)

    def unlink(self):
        if any(item.state != "draft" for item in self):
            raise AccessError(_("Confirmed or revoked evidence is retained for audit."))
        return super().unlink()

    def action_confirm(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        self.invalidate_recordset()
        if (
            self.state != "draft"
            or self.expires_at <= fields.Datetime.now()
            or not self.evidence.strip()
        ):
            raise UserError(
                _("Confirm a draft with current, non-empty authorization evidence."),
            )
        if not self.namespace.strip() or not self.recipient.strip():
            raise UserError(_("Recipient identity and namespace are required."))
        super().write(
            {
                "state": "confirmed",
                "confirmed_by": self.env.uid,
                "confirmed_at": fields.Datetime.now(),
            },
        )
        self._audit(
            "recipient.confirmed", _("Recipient authorization evidence confirmed."),
        )
        return True

    def action_revoke(self):
        self.ensure_one()
        self._require_manager()
        self.channel_id._lock()
        self.invalidate_recordset()
        if self.state != "confirmed":
            raise UserError(_("Only confirmed evidence can be revoked."))
        super().write({"state": "revoked"})
        self._audit(
            "recipient.revoked",
            _(
                "Authorization withdrawn. Unclaimed work will be held; in-flight work may complete.",
            ),
        )
        return True


class OmniAttempt(models.Model):
    _name = "omni.attempt"
    _inherit = ["omni.scope.mixin"]
    _description = "Outbound Dispatch Attempt"
    _order = "id desc"

    command_id = fields.Many2one(
        "omni.command", required=True, ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        related="command_id.company_id", store=True, precompute=True, default=None,
    )
    purpose_id = fields.Many2one(
        related="command_id.purpose_id", store=True, precompute=True,
    )
    number = fields.Integer(required=True)
    token = fields.Char(required=True, readonly=True, groups="base.group_no_one")
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    ended_at = fields.Datetime(readonly=True)
    outcome = fields.Selection(
        [
            ("dispatching", "In flight"),
            ("accepted", "Accepted by provider"),
            ("definitely_not_sent", "Not sent"),
            ("unknown", "Outcome unknown"),
        ],
        default="dispatching",
        required=True,
        readonly=True,
    )
    reason_code = fields.Char(readonly=True)
    provider_message_key = fields.Char(readonly=True)
    _number_unique = models.Constraint(
        "UNIQUE(command_id, number)", "Attempt numbers must be unique per command.",
    )
    _token_unique = models.Constraint(
        "UNIQUE(token)", "Dispatch tokens must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not is_internal(self):
            raise AccessError(_("Only the worker can create dispatch evidence."))
        return super().create(vals_list)

    def write(self, vals):
        if not is_internal(self) or any(
            attempt.outcome != "dispatching" for attempt in self
        ):
            raise AccessError(_("Completed dispatch attempts are immutable."))
        if vals.keys() - {"ended_at", "outcome", "reason_code", "provider_message_key"}:
            raise AccessError(_("Attempt identity cannot be changed."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_("Dispatch evidence cannot be deleted."))


class OmniDispatchCommand(models.Model):
    _inherit = "omni.command"

    state = fields.Selection(
        selection_add=[
            ("dispatching", "Sending"),
            ("accepted", "Accepted by provider"),
            ("unknown", "Outcome unknown"),
            ("failed", "Failed"),
            ("expired", "Expired"),
        ],
        ondelete={
            key: "set default"
            for key in ("dispatching", "accepted", "unknown", "failed", "expired")
        },
    )
    next_attempt_at = fields.Datetime(readonly=True, copy=False)
    attempt_count = fields.Integer(readonly=True, copy=False)
    lease_token = fields.Char(readonly=True, copy=False, groups="base.group_no_one")
    lease_expires_at = fields.Datetime(readonly=True, copy=False)
    attempt_ids = fields.One2many("omni.attempt", "command_id", readonly=True)
    current_attempt_id = fields.Many2one(
        "omni.attempt", readonly=True, copy=False, ondelete="restrict",
    )
    provider_message_key = fields.Char(readonly=True, copy=False)
    reconciliation_evidence = fields.Text(readonly=True, copy=False)
    _due_index = models.Index("(state, next_attempt_at, id)")
    _protected = OmniCommand._protected | {
        "next_attempt_at",
        "attempt_count",
        "lease_token",
        "lease_expires_at",
        "attempt_ids",
        "current_attempt_id",
        "provider_message_key",
        "reconciliation_evidence",
    }

    def _lock(self):
        # Universal lock order: channel -> command -> attempt. Sender changes
        # already lock the channel before holding queued commands.
        self.ensure_one()
        self.channel_id._lock()
        return super()._lock()

    def action_cancel(self):
        self.ensure_one()
        self.check_access("read")
        self._lock()
        if self.state in ("dispatching", "unknown", "accepted"):
            raise UserError(
                _("An in-flight, unknown or accepted send cannot be cancelled locally."),
            )
        return super().action_cancel()

    def _check_dispatch_authorization(self):
        self.ensure_one()
        self._check_frozen()
        request = self.approval_request_id.sudo()
        doc = self._policy_document()
        if (
            request.state != "approved"
            or request.omni_command_id != self
            or request.target_model != "omni.command"
            or request.target_res_id != self.id
            or request.company_id != self.company_id
            or request.requester_id != self.requester_id
        ):
            raise AccessError(_("Approval evidence does not match this command."))
        lines = request.approver_ids
        expected = {uid for uid, sequence, required in doc["approvers"]}
        approved = set(
            lines.filtered(lambda item: item.status == "approved").user_id.ids,
        )
        required = {uid for uid, sequence, required in doc["approvers"] if required}
        if (
            set(lines.user_id.ids) != expected
            or len(approved) < doc["minimum"]
            or not required.issubset(approved)
        ):
            raise AccessError(_("Required approvals are missing."))
        # Explicit recipient grant is required even for an approved command.
        if (
            not self.env["omni.consent"]
            .sudo()
            .search_count(
                [
                    ("channel_id", "=", self.channel_id.id),
                    ("namespace", "=", self.sender_id.namespace),
                    ("recipient", "=", self.recipient),
                    ("state", "=", "confirmed"),
                    ("expires_at", ">", fields.Datetime.now()),
                ],
            )
        ):
            raise AccessError(
                _("Current recipient authorization evidence is required."),
            )

    @api.model
    def _claim_next(self):
        """Caller owns the transaction and MUST commit the returned claim before I/O."""
        if not self.env.su:
            raise AccessError(_("Only the isolated worker can claim dispatch work."))
        now = fields.Datetime.now()
        self.env.flush_all()
        # Suppression changes lock the company before channels. Reserve the same
        # boundary without waiting; this also serializes accidentally concurrent workers.
        self.env.cr.execute("""
            SELECT company.id FROM res_company company WHERE EXISTS (
                SELECT 1 FROM omni_channel c JOIN omni_command cmd ON cmd.channel_id = c.id
                WHERE c.company_id = company.id AND c.active AND c.dispatch_enabled
                  AND cmd.state = 'queued'
                  AND (cmd.next_attempt_at IS NULL OR cmd.next_attempt_at <= %s)
                  AND (c.next_dispatch_at IS NULL OR c.next_dispatch_at <= %s)
                  AND (c.circuit_until IS NULL OR c.circuit_until <= %s)
                  AND NOT EXISTS (SELECT 1 FROM omni_command busy WHERE busy.channel_id = c.id
                      AND busy.state IN ('dispatching', 'unknown')))
            ORDER BY company.id LIMIT 1 FOR UPDATE SKIP LOCKED
        """, [now, now, now])
        company_row = self.env.cr.fetchone()
        if not company_row:
            return None
        self.env.cr.execute(
            """
            SELECT channel.id FROM omni_channel channel
            WHERE channel.company_id = %s AND channel.active AND channel.dispatch_enabled
              AND (channel.next_dispatch_at IS NULL OR channel.next_dispatch_at <= %s)
              AND (channel.circuit_until IS NULL OR channel.circuit_until <= %s)
              AND NOT EXISTS (SELECT 1 FROM omni_command busy
                  WHERE busy.channel_id = channel.id AND busy.state IN ('dispatching', 'unknown'))
              AND EXISTS (SELECT 1 FROM omni_command due
                  WHERE due.channel_id = channel.id AND due.state = 'queued'
                    AND (due.next_attempt_at IS NULL OR due.next_attempt_at <= %s))
            ORDER BY channel.next_dispatch_at NULLS FIRST, channel.id
            LIMIT 1 FOR UPDATE OF channel SKIP LOCKED
        """,
            [company_row[0], now, now, now],
        )
        row = self.env.cr.fetchone()
        if not row:
            return None
        channel_id = row[0]
        self.env.cr.execute(
            """
            SELECT id FROM omni_command WHERE channel_id = %s AND state = 'queued'
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY next_attempt_at NULLS FIRST, id LIMIT 1 FOR UPDATE SKIP LOCKED
        """,
            [channel_id, now],
        )
        row = self.env.cr.fetchone()
        if not row:
            return None
        command = self.browse(row[0])
        command.invalidate_recordset()
        command = command.with_context(allowed_company_ids=[command.company_id.id])
        try:
            command._check_dispatch_authorization()
        except (AccessError, UserError):
            state = (
                "expired"
                if command.expires_at and command.expires_at <= now
                else "held"
            )
            internal(command).write(
                {
                    "state": state,
                    "held_reason": _(
                        "Authorization, recipient evidence or configuration changed. Submit a fresh review.",
                    ),
                },
            )
            command._audit(
                "dispatch.held",
                _("Current dispatch authorization failed. No provider invocation."),
            )
            return False
        token = str(uuid.uuid4())
        attempt = internal(self.env["omni.attempt"]).create(
            {
                "command_id": command.id,
                "number": command.attempt_count + 1,
                "token": token,
            },
        )
        internal(command).write(
            {
                "state": "dispatching",
                "attempt_count": attempt.number,
                "current_attempt_id": attempt.id,
                "lease_token": token,
                "lease_expires_at": now + timedelta(seconds=120),
                "held_reason": False,
            },
        )
        internal(command.channel_id).write(
            {
                "next_dispatch_at": now
                + timedelta(seconds=command.channel_id.dispatch_interval_seconds),
            },
        )
        command._audit(
            "dispatch.claimed", _("Dispatch authorized and attempt reserved."),
        )
        account = command.sender_id.account_id
        return DispatchClaim(
            command.id,
            attempt.id,
            token,
            command.uuid,
            command.channel_id.channel_type_id.code,
            json.dumps(command.payload, sort_keys=True),
            account.external_account_key,
            account.namespace,
            command.sender_id.external_key,
            account.credential_reference or "",
            json.dumps(account._adapter_config(), sort_keys=True),
        )

    def _finish_attempt(self, claim, raw_result):
        self.ensure_one()
        if not self.env.su:
            raise AccessError(_("Only the worker can complete dispatch evidence."))
        self._lock()
        if (
            self.state != "dispatching"
            or self.lease_token != claim.token
            or self.current_attempt_id.id != claim.attempt_id
            or self.id != claim.command_id
        ):
            return False
        result = normalize_result(raw_result)
        now = fields.Datetime.now()
        vals = {"lease_expires_at": False, "lease_token": False}
        if result.outcome == "accepted":
            vals.update(
                state="accepted",
                provider_message_key=result.provider_message_key,
                held_reason=False,
            )
        elif result.outcome == "unknown":
            vals.update(
                state="unknown",
                held_reason=_(
                    "The provider may have accepted this message. Reconcile before any replacement.",
                ),
            )
        else:
            delay = max(
                1,
                result.retry_after,
                random.uniform(0, min(900, 5 * 2 ** (self.attempt_count - 1))),
            )
            due = now + timedelta(seconds=delay)
            if result.retryable and self.attempt_count < 5 and due < self.expires_at:
                vals.update(
                    state="queued",
                    next_attempt_at=due,
                    held_reason=_(
                        "Provider confirmed no send; a bounded retry is scheduled.",
                    ),
                )
            else:
                vals.update(
                    state="failed",
                    held_reason=_(
                        "Provider confirmed no send. Retry is not authorized or its budget expired.",
                    ),
                )
        internal(self.current_attempt_id).write(
            {
                "ended_at": now,
                "outcome": result.outcome,
                "reason_code": result.reason_code,
                "provider_message_key": result.provider_message_key,
            },
        )
        internal(self).write(vals)
        channel = self.channel_id
        if result.reason_code in ("transport", "unhealthy", "unauthorized"):
            count = (
                channel.failure_count + 1
                if channel.failure_window_start
                and now - channel.failure_window_start < timedelta(minutes=5)
                else 1
            )
            updates = {"failure_count": count}
            if count == 1:
                updates["failure_window_start"] = now
            if count >= 5:
                updates["circuit_until"] = now + timedelta(minutes=5)
            internal(channel).write(updates)
        elif result.outcome == "accepted":
            internal(channel).write(
                {
                    "failure_count": 0,
                    "failure_window_start": False,
                    "circuit_until": False,
                },
            )
        if result.retry_after:
            internal(channel).write(
                {
                    "next_dispatch_at": max(
                        channel.next_dispatch_at or now,
                        now + timedelta(seconds=result.retry_after),
                    ),
                },
            )
        if result.reason_code in ("unhealthy", "unauthorized"):
            super(OmniSender, self.sender_id).write(
                {
                    "health": "unhealthy",
                    "health_checked_at": now,
                    "health_message": _(
                        "Dispatch verification failed. Administrator action required.",
                    ),
                },
            )
        self._audit(
            "dispatch." + result.outcome,
            _("Dispatch outcome recorded; consult the attempt status."),
        )
        return True

    @api.model
    def _recover_expired(self, limit=50):
        if not self.env.su:
            raise AccessError(_("Only the worker can recover expired attempts."))
        self.env.flush_all()
        now = fields.Datetime.now()
        self.env.cr.execute(
            """
            SELECT company.id FROM res_company company WHERE EXISTS (
                SELECT 1 FROM omni_command cmd WHERE cmd.company_id = company.id
                AND cmd.state = 'dispatching' AND cmd.lease_expires_at <= %s)
            ORDER BY company.id LIMIT %s FOR UPDATE OF company SKIP LOCKED
        """,
            [now, max(1, min(int(limit), 50))],
        )
        company_ids = [row[0] for row in self.env.cr.fetchall()]
        commands = self.search(
            [
                ("company_id", "in", company_ids),
                ("state", "=", "dispatching"),
                ("lease_expires_at", "<=", now),
            ],
        )
        for command in commands:
            command._lock()
            internal(command.current_attempt_id).write(
                {"outcome": "unknown", "ended_at": now, "reason_code": "lease_expired"},
            )
            internal(command).write(
                {
                    "state": "unknown",
                    "lease_token": False,
                    "lease_expires_at": False,
                    "held_reason": _(
                        "Worker lease expired. Sending again could duplicate an accepted message.",
                    ),
                },
            )
            command._audit(
                "dispatch.unknown", _("Worker lease expired; reconciliation required."),
            )
        return len(commands)

    @api.model
    def _cron_dispatch(self, limit=10):
        """Only the cron wrapper owns commits. No HTTP/approval transaction sends."""
        if not self.env.su:
            raise AccessError(_("Only the system worker can run dispatch."))
        registry = self.env.registry
        deadline = time.monotonic() + 45
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["omni.command"]._recover_expired()
            cr.commit()
        for _index in range(max(1, min(int(limit), 50))):
            if time.monotonic() >= deadline:
                break
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                claim = env["omni.command"]._claim_next()
                cr.commit()  # Durable authorization precedes any provider I/O.
            if claim is None:
                break
            if claim is False:
                continue
            result = dispatch_claim(claim)  # No DB transaction and no automatic retry.
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["omni.command"].browse(claim.command_id)._finish_attempt(
                    claim, result,
                )
                cr.commit()  # Failure leaves a committed in-flight attempt to recover.

    def action_open_reconciliation(self):
        self.ensure_one()
        self._require_manager()
        if self.state != "unknown":
            raise UserError(_("Only unknown outcomes need reconciliation."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reconcile unknown outcome"),
            "res_model": "omni.reconciliation",
            "view_mode": "form",
            "target": "new",
            "context": {"default_command_id": self.id},
        }


class OmniReconciliation(models.TransientModel):
    _name = "omni.reconciliation"
    _description = "Reconcile Dispatch Outcome"

    command_id = fields.Many2one("omni.command", required=True, readonly=True)
    outcome = fields.Selection(
        [("accepted", "Verified accepted"), ("not_sent", "Verified not sent")],
        required=True,
    )
    provider_message_key = fields.Char()
    evidence = fields.Text(
        required=True,
        help="Provider evidence identifying this exact command and its actual outcome.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.check_access("read")
        command = self.command_id
        command._require_manager()
        command._lock()
        if command.state != "unknown" or not self.evidence.strip():
            raise UserError(
                _("An unknown command and explicit verification evidence are required."),
            )
        if self.outcome == "accepted":
            from odoo.addons.omni_channel.providers.dispatch import DispatchResult  # noqa: PLC0415

            verified = normalize_result(
                DispatchResult(
                    "accepted", provider_message_key=self.provider_message_key or "",
                ),
            )
            if verified.outcome != "accepted":
                raise UserError(
                    _(
                        "Enter a valid provider message identifier for the verified acceptance.",
                    ),
                )
        # Never edit old attempt evidence or requeue from an operator assertion.
        internal(command).write(
            {
                "state": "accepted" if self.outcome == "accepted" else "failed",
                "provider_message_key": self.provider_message_key
                if self.outcome == "accepted"
                else False,
                "reconciliation_evidence": self.evidence,
                "held_reason": False,
            },
        )
        command._audit(
            "dispatch.reconciled",
            _("Administrator recorded provider evidence. No resend was performed."),
        )
        return {"type": "ir.actions.act_window_close"}
