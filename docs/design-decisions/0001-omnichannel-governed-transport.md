# ADR 0001: Governed Omni-Channel transport

Date: 2026-10-05.
Status: selected for implementation planning under the user's request to resolve plan gaps; no live policy or deployment is activated.

## Context

The original Omni-Channel package specified exclusive inbound ownership and a single runtime sender, but mixed business module/record identifiers, company scopes, approval states and delivery guarantees. Later additions introduced sender pools and blocking without reconciling the earlier models or pipeline. Existing Approval Center provides a review surface but needs an Omni-specific execution contract.

## Decision

Use company + stable business purpose + channel type as logical ownership. Preserve one selected sender and prohibit hidden alternate-identity replies. Keep incompatible conversations receive-only until a compatible sender is explicitly selected or new outreach is separately approved.

Represent approved work as immutable versioned commands. Reuse Approval Center with scoped hardening, then queue commands in PostgreSQL for controlled Odoo cron dispatch. Separate approval, local execution and provider delivery. An ambiguous external effect is unknown, not automatically retryable. Sender changes invalidate pending commands from previous channel generations.

Resolve trusted inbound ownership before scoped blocking and before business side effects. An explicit activated ingestion policy permits only local transport processing; business workflows and external AI disclosure need separate authorization. Namespace identities and version endpoint assignments. Company-wide blocking never crosses company boundaries.

Use a modular monolith: core, optional provider addons and optional business bridges. Begin with a mock adapter and private Telegram text. Keep the twelve-platform catalog, but disable capabilities without implementation and verified evidence. Email/SMS remain native. No mandatory broker, vector database, AI service or Enterprise addon is introduced.

## Alternatives considered

- Per-conversation reply sender: more flexible, but violates the explicit single-runtime-sender requirement. A future product change would require a new ADR and revised approvals/security tests.
- Resolve active sender only at delivery: simpler, but allows identity changes after human review. Rejected in favor of pinned generation and reapproval.
- Send in the approval transaction: simple UI, but rollback cannot recall an external send. Rejected.
- Assume an outbox gives exactly-once delivery: false for non-idempotent provider APIs. Use uncertainty/reconciliation.
- New standalone approval engine: duplicates the existing product surface. Use narrowly scoped integration hardening.
- Broker-first microservices and all providers at once: adds infrastructure and broad unverified surface before the invariants are tested. Defer until measured need.

## Consequences

Some multi-inbound conversations cannot be replied to under the currently selected identity. This limitation is deliberate and visible. Approval and provider states remain independently understandable. Unknown outcomes and restore recovery require operator reconciliation. Future adapters need individual API and account-access evidence. The first implementation can proceed without live credentials, but production cannot.

## Contracts and verification

See the [revised plan](../exec-plans/active/odoo_omnichannel_design_v2/README.md), [research record](../exec-plans/active/odoo_omnichannel_design_v2/13-research-and-provider-readiness.md), and [acceptance matrix](../exec-plans/active/odoo_omnichannel_design_v2/12-acceptance-and-release.md). T01-T27 trace the decisions to implementation evidence. Planning completion does not mean those tests have passed.
