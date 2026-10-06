# Core rules — normative

## Ownership and cardinality

- `omni.purpose` is a stable business purpose (marketing, sales, recruitment, hr), not an installed module ID or individual business record.
- `omni.channel` has required company, purpose and channel type; UNIQUE(company_id, purpose_id, channel_type_id), including archived records. Restore a channel instead of duplicating it.
- A channel has 0..N outbound configurations and 0..1 selected runtime sender. Zero means outbound unavailable. Odoo `active` means archived/unarchived; `is_selected` means runtime selection. Never overload `active`.
- A channel has 0..N inbound endpoints. An inbound-only channel is valid.
- Each physical endpoint is owned by one company and purpose across this database. Uniqueness uses channel type + canonical provider namespace + external endpoint key, not credential record ID. Two connections to the same external account do not create a second ownership namespace.
- Endpoint keys have required non-null normalized components. Archive does not free ownership. Explicit reassignment changes ownership on the existing endpoint; history is preserved.
- Accounts and sender identities are company-owned. A sending identity is assigned to only one logical channel at a time. Cross-purpose sharing of the same sending identity is out of scope.
- Endpoint/account/sender/channel company and channel type must agree. Provider namespace is adapter-produced and administrator-verified, never accepted from an untrusted caller.

## Selection and reply semantics

Activation requires configuration permission, explicit Check & Activate confirmation, a fresh real provider health check and audit. A failed check preserves the old selection. Selection uses a channel row lock and a partial unique index on `(channel_id) WHERE is_selected`. Reject selection of an archived sender.

No automatic failover. An unhealthy selected sender remains selected for diagnosis but cannot send. Health is a readiness observation, not proof every future operation will succeed. Capabilities and recipient eligibility are checked for each command.

All outbound, including replies, resolves the selected sender. Replies require the adapter to validate that this sender can address the original conversation. If identity/thread continuity cannot be established, block the reply. Do not use the inbound identity as a hidden alternate sender. A user may explicitly prepare a new conversation through the selected sender when provider rules permit; it requires a new approval and is not represented as a reply.

An approved command pins sender identity and channel generation. Switching sender invalidates unsent commands from the prior generation, even if the sender is later switched back. Explicitly clone and resubmit them. Selection changes wait for in-flight commands to settle; uncertain outcomes require reconciliation first.

## Authorization and automation

AI never grants permission. Every execution independently checks identity, role, company, purpose, business-record access, capability, current consent and approval. Direct RPC, imports, cron and adapter calls must not bypass these gates.

Default external sending requires an Approval Center request and a distinct authorized approver. Configured governance actions (activate/deactivate, block/unblock, enable inbound policy, reassignment) use explicit authorized human confirmation and audited scope; AI proposals cannot call their execution methods.

A human-activated inbound policy permits verified event ingestion, local conversation/message persistence and assigned-team UI updates only. Contact/lead creation, workflow transitions, external AI disclosure and replies are denied unless a separate reviewed policy or approval authorizes them. Installing a module enables no real ingestion policy or outbound automation.

## Canonical inbound order

Verify raw request -> bounded parse -> resolve trusted account and endpoint ownership -> normalize identity in memory -> company/purpose block check -> persist minimal blocked evidence OR durable allowed event -> acknowledge -> asynchronous moderation/routing -> conversation/message -> separately authorized business effects.

Resolve ownership before module-scoped blocking, without creating partners or conversations. Unknown endpoints are quarantined and never routed by guesswork. A valid unknown event is retained only in restricted quarantine. Receipt/status events reconcile deliveries and do not create conversations or run content moderation.

## Reliability

At-least-once ingestion with deduplication; durable commands before any external send. Do not claim universal exactly-once provider delivery. Unknown send outcomes are held for reconciliation. No blind retry where provider acceptance is uncertain and no documented idempotency contract exists.

## Change control

Reassignment, credential identity changes, capability grants and policy changes are auditable and versioned. Old business records are never silently moved between purposes/companies. Cross-company endpoint transfer is not supported in the initial releases.
