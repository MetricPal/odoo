# Coding brief

Implement incrementally from the revised package, beginning with P0 in [phases](07-implementation-phases.md). This document does not authorize live configuration, credentials, provider sends or deployment. Follow the user's current implementation authorization and project governance.

Read AGENTS.md and project contracts, the applicable `.codex/skills/` instructions, then this package's README and normative documents 02, 03, 04, 08, 11 and 12. Read research/decision records before choosing APIs. Resolve new discoveries in documentation instead of silently overriding architecture.

Mandatory invariants:

- Odoo 20 Community source is authority for APIs; use the current `ir.access` model and supported ORM/index mechanisms.
- Company + purpose + channel type identifies one logical channel. Multiple sender configurations, at most one selected, 0..N exclusive inbound endpoints.
- No automatic failover, no inactive-sender replies, no sender substitution after approval.
- Use existing Approval Center with the specified Omni-scoped hardening; immutable approved command and durable asynchronous execution.
- Normalized adapters behind a trusted registry; no invented capabilities, credentials or successful live health.
- Verify -> resolve ownership -> normalize identity -> block check -> persist/ack -> asynchronous processing.
- Unknown outcomes do not blindly retry; successful local database rollback cannot undo a provider send.
- No Enterprise dependency, no duplicate email/SMS engine, no mandatory external broker/AI runtime.
- Human-activated policies authorize inbound record processing; business record creation and external model disclosure are separate grants.
- Default portal/public model access is none; company/purpose/business access applies to every surface.

Build tests alongside each increment using the T01-T27 matrix; record actual test evidence. Add native usable UI and documentation with each phase, not only at the end. First live adapter is private Telegram text only, gated by sandbox prerequisites. Future capabilities stay visibly unavailable until individually verified.

Before completion report code changes, behavior, tests/security/UI evidence, migration implications and remaining release gates. Do not claim production readiness from mocks or describe planned tests as executed.
