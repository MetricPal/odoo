# Odoo 20 Community integration

Source baseline: `dbce1c66c4d1f9779f55d82657e8214d2c09654b`, inspected 2026-10-05. Recheck against the checkout when coding. Evidence and external references: [research](13-research-and-provider-readiness.md).

## Addon boundaries

- `omni_channel`: core, mock adapter restricted to tests/demo, governance integration, native views. Dependencies: base, mail, bus, web, approval_center. Approval Center transitively requires hr in this checkout; accept and document this initial footprint rather than refactoring it silently.
- `omni_channel_telegram`: optional first adapter; depends on core. Core has no direct provider HTTP logic.
- Later optional adapters: whatsapp, slack, discord, and individual social providers.
- Later bridges: `omni_channel_crm`, `omni_channel_hr_recruitment`, etc. Depend on core and their business addon. Core must install without CRM, Recruitment or every provider.
- Optional moderation addon depends on core and a configured AI service. No LLM dependency or external model calls at core installation.

Use native Email Marketing (`mass_mailing`), `mail`, and `sms` as their existing owners. Local `social_media` only provides company social configuration; it is not the documented full Social Marketing publishing engine. Do not depend on unavailable Enterprise models or duplicate an assumed native service.

## Verified source contracts

| Concern | Local source | Implementation decision |
|---|---|---|
| Authorization | odoo/addons/base/models/ir_access.py | `ir.access`, operation and domain fields; group-less restrictions AND grouped grants, not legacy ir.model.access CSV |
| ORM authorization | odoo/orm/models.py | `check_access()` / `has_access()`; verify underlying business access under requester identity |
| Constraints | odoo/orm/table_objects.py | Constraint and partial UniqueIndex; transactional locks still required |
| Scheduled work | odoo/addons/base/models/ir_cron.py | bounded batches, `_commit_progress()` only at intentional worker boundaries; `_trigger()` for wakeup |
| Webhook controller example | addons/payment_stripe/controllers/main.py | HTTP POST raw-body verification, constant-time comparison, replay checks where protocol supports them; do not copy its payload logging |
| UI bus | addons/bus/models/bus.py and bus_listener_mixin.py | prefer authorized listener channels; payload IDs only, refetch with access checks |
| Approval execution | addons/approval_center/models/approval_center_request.py | integrate existing request UI; harden Omni-linked execution before live use |
| Media | ir.attachment | use private attachments with parent record access; do not expose public bearer URLs |

Odoo 20 frontend in this checkout uses Owl 3. Start with native list/form/search/kanban views; verify component APIs locally before building a custom composer or radio selector. Existing repository verification notes describe `useProps`, `proxy` and signal references. Do not import familiar Owl 2 patterns blindly.

## Approval Center integration prerequisite

Current code invokes a configured public action, checks approved state and policy-model match, then records execution time. These observations do not establish secure one-shot asynchronous execution. It uses policy-related fields that can change, audit children cascade on parent deletion, and a failed action is audited then re-raised in the same transaction (that audit can roll back).

Implement a narrowly scoped extension for Omni-linked requests:

1. Require company agreement, exact `omni.command` target and allowlisted `action_enqueue_approved`; reject alternate model/method/record substitutions.
2. Snapshot policy version, approver membership/sequence/minimum, requester, payload hash and command revision at submission. Disallow requester self-approval for external sends. Guard ORM create/write/unlink, not just readonly form fields.
3. Make protected approval fields and approver lines immutable after submission except through validated review actions. Policy changes invalidate outstanding approvals; they cannot retroactively weaken them.
4. Lock approval and command when enqueuing; require actual approval evidence and current authorized access. One approval authorizes one command revision. Repeated execution returns the existing queue result.
5. Approval execution means durable enqueue, not successful external delivery. Display these separately; provider result lives on command/delivery/attempt records.
6. Persist worker failure/audit in a controlled transaction after handling errors; never assume audit survives a raised transaction rollback. Keep rejected-call security logs sanitized.
7. Restrict company and purpose access on Omni-linked requests, approver lines, attachments and audits; existing generic manager rights cannot widen Omni visibility.
8. Preserve existing non-Omni approval behavior and add regression tests. Do not redesign the entire Approval Center as part of this integration.

## Business integration API

`prepare_command(channel_id, operation, recipient, content, client_request_key, conversation_id=None)` prepares only. Derive company/purpose from accessible channel, never a free client module string. `action_submit()` opens a business-named approval request. `action_enqueue_approved()` verifies evidence and writes the durable outbox. Only the worker dispatches external operations.

Inbound bridge methods receive normalized, authorized events. Default bridge only links existing permitted records on explicit user choice. Automatic creation requires a separately activated deterministic policy and idempotency key. No provider adapter chooses Odoo models or invokes business methods.
