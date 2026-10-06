# Implementation specification — normative

Read [core rules](02-core-rules.md), [model](03-data-model.md), [Odoo integration](04-odoo-integration.md), [security](11-security-and-operations.md) and [tests](12-acceptance-and-release.md) together. This is the coding contract, not executable code.

## Provider boundary

Adapters are installed Python services registered by trusted addon code. No provider-specific HTTP in core models and no dynamic imports from database strings. Adapters have no authority to select a company, read arbitrary Odoo records or approve actions. Inject transport and secret resolver; private dispatch entry points cannot be called through generic RPC.

Versioned immutable DTOs:

- `VerifiedEnvelope(account_key, provider_event_key, received_at, raw_hash, events)`; signature validation uses original bytes before transformations.
- `NormalizedEvent(schema_version, kind, endpoint_key, identity_namespace, sender_key, thread_key, message_key, occurred_at, content, receipt, metadata)`; one envelope may contain several separately deduplicated events.
- `PreparedCommand(schema_version, uuid, company, purpose, channel, generation, sender_key, account_key, operation, recipient_key, conversation_key, content, attachment_checksums, template_version, schedule, expiry, policy_version)`.
- `HealthResult(status, checked_at, account_key, sender_key, config_version, capability_evidence, safe_reason)`.
- `DispatchResult(outcome, provider_message_key, retry_after, safe_error_code, safe_error_summary)`; outcome is accepted / definitely_not_sent / unknown. Never infer delivered from accepted.

Adapter methods: `verify_request(raw_body, headers, account_config)`, `normalize(envelope)`, `check_sender_health(sender_config)`, `capabilities(account_config)`, `validate_command(command)`, `dispatch(command, idempotency_key)`, optional `reconcile(command, evidence)`. Network operations have bounded connect/read timeouts. Health checks must be read-only; webhook registration and other external setup operations are separate confirmed commands.

Every adapter declares namespace/key rules, signature/token verification, event types, API version, rate buckets, error classification, outbound idempotency/reconciliation support and sender continuity rules. Missing behavior fails closed. Do not assume HTTP 5xx implies the message was not accepted.

## Preparation, approval and enqueue

1. Access channel and any business/conversation records as requester with one explicit company context. Reject arbitrary destination model/method input.
2. Resolve selected sender and generation; normalize operation/recipient/content; validate capabilities, eligibility and consent. Prepared draft has no external effect.
3. Canonicalize UTF-8 JSON with stable key ordering, UTC timestamps, explicit nulls and schema version; SHA-256 covers all meaningful fields and attachment digests. Exclude volatile health timestamps and secrets. Store the canonical document, not just its hash.
4. Submit creates an Approval Center request linked to one frozen revision. Show full recipients/content/media/sender/schedule, reason and scope. Snapshot approver/policy evidence. ORM writes to protected content are denied after submission; edits clone a new revision and invalidate the old one.
5. Enqueue locks request and command in deterministic order, rechecks approval evidence/current permissions and inserts queue state atomically. Unique company/client_request_key handles caller retries; same key with different content is an error. Repeated approval execution returns the same command.
6. Default approval expires after 24 hours. Explicit future schedule is included in approval, whose expiry must cover the intended execution interval; show expiry to the approver. No implicit extension. Current policy changes, revocation or sender generation changes hold unsent work.

Public actions are thin validated entry points. Internal worker methods never accept an `approved=True` flag from RPC/context as proof. Forged approval state, imported records, edited approver lines and direct `write()` are negative-test cases.

## Outbound transactions and concurrency

Use PostgreSQL as the durable outbox and Odoo cron as the initial worker. No required broker. External network calls never run in the originating UI/approval transaction or an automatically retried ORM transaction.

Worker algorithm:

1. Claim due queue rows in small batches using `FOR UPDATE SKIP LOCKED` in a worker-owned transaction. Lock command/channel consistently. Resolve company/requester from immutable command, not cron user permissions alone.
2. Recheck approval, permissions, current suppression, account config and channel generation. If any precondition changed, hold or invalidate without sending. Claim an attempt UUID and record `dispatching`, lease and pinned sender; commit before network I/O. This committed dispatch authorization is the linearization point. A later cancellation cannot promise to recall an in-flight network request.
3. Do a bounded health/eligibility preflight if cached health is too old; no send if preflight fails. Initial maximum health age: 60 seconds at dispatch, fresh at activation. These are operational defaults, not provider guarantees. Credentials rotated under the same verified sender identity may refresh transport; changed external identity invalidates approval.
4. Perform exactly one transport invocation per attempt. Persist outcome in a fresh worker transaction after checking attempt token; a stale worker cannot overwrite a newer result. Known acceptance records provider ID before any follow-up. Database failure after provider acceptance becomes an uncertain outcome on recovery.
5. Lease default 120 seconds with hard HTTP connect/read limits 5/20 seconds; no automatic resend merely because a lease expired. Expired dispatching attempts become unknown and go to reconciliation. Workers must not wrap the provider call in Odoo request retry logic.
6. Retry only documented definitely-not-sent outcomes, or documented provider idempotent replay using the same stable UUID within its validity period. Full-jitter bounded exponential delay: initial 5 seconds, cap 15 minutes, maximum 5 attempts by default, bounded by command expiry. Respect provider Retry-After as a minimum. Permission/validation failures are terminal or held; 429 follows adapter classification; timeouts after possible dispatch are unknown.
7. Keep channel selection fixed while any attempt is dispatching or unknown. Activation detects these states and returns a clear hold reason. Health checking a prospective sender is outside the selection lock; lock and recheck account/config versions, the channel generation captured at confirmation, and check freshness before atomically switching. A stale concurrent confirmation must refresh rather than overwrite another administrator's choice. Increment generation and hold old queued commands in that transaction.
8. Account revocation/emergency pause prevents future claims immediately. In-flight requests may finish; UI and audit must state this limitation. Do not attempt unsafe external compensation automatically.

Rate limiting is persistent and account/provider-bucket scoped, not one in-memory counter per worker. Atomically reserve capacity before dispatch. Retry budgets and circuit breakers pause the same sender; they never switch senders. Implement one worker initially, but database claims/indexes must be safe if two are started accidentally.

## Inbound transaction boundaries

Ingress is HTTPS, database-resolved by server routing rather than an untrusted database parameter. Resolve a secret reference from a trusted webhook route configuration. Verify original bytes; reject invalid signatures/tokens without saving content. Bounded parse produces normalized envelope identifiers only; no AI or media fetch in HTTP handler.

Under the enabled ingestion policy, resolve endpoint company/purpose and ownership version without creating contacts. Check global-within-company and purpose blocks. Blocked messages retain keyed identity hash, event key, timestamp and reason, no body/media. Unblocked payloads enter a restricted durable inbox. Deduplicate with a database unique key; safely acknowledge duplicates after rollback-to-savepoint where needed. An event with reused ID but changed payload hash is quarantined as an anomaly. Commit successfully before a 2xx response; persistence failure returns retriable 5xx. Challenge requests are handled by the adapter without business effects.

Worker rechecks policy, endpoint ownership version and blocklist, because these may have changed after receipt. New blocks purge pending content under retention policy. Unknown endpoints and ownership-version mismatches are quarantined. Normalize identity in memory before creating an identity row. In one transaction, create normalized message/conversation/participant and mark event processed. Bridge effects use their own authorized idempotent job. Publish only permitted refresh IDs after commit.

Inbound delivery/status events bypass conversation/moderation but still require verification, company resolution and dedup. Out-of-order delivery events append evidence; derive state without regressing read to delivered or treating an earlier failure as final after confirmed success. Uncorrelated receipts remain restricted pending reconciliation.

## State machines

| Entity | States / transitions |
|---|---|
| Approval | existing to_submit -> submitted -> approved/refused; Omni validity additionally valid/expired/revoked/invalidated |
| Command | draft -> pending_approval -> approved -> queued -> dispatching -> accepted; branches held, expired, cancelled, failed, unknown |
| Retry | definitely-not-sent dispatching -> queued if budget/time remain; unknown -> accepted or verified-not-sent; no unverified unknown -> queued |
| Event | received -> processing -> processed; branches blocked, unresolved, retry, dead; replay requires authorized operator and same idempotency key |
| Delivery | pending -> accepted -> delivered -> read when provider evidence exists; independent failed/unknown evidence |
| Conversation | new/open/waiting/closed; closing does not delete messages or recall sends |

Operational status and approval status are separate fields. Direct writes to protected states are denied outside server transition methods. Concurrency guards and evidence checks enforce transitions.

## Endpoint reassignment

Until the full workflow exists, activated endpoint ownership is immutable. Later workflow: disable intake, wait for processing/dispatch or quarantine old jobs, inventory open conversations and blocks, require old/new purpose authorization, confirm impact, append assignment history, increment ownership version, enable new policy explicitly. Pending old-version events stay with old ownership or quarantined; never silently move. Old conversations remain readable only to original authorized users. Blocks are not copied automatically; operator reviews new scope. Cross-company transfers remain unsupported.

## Bulk and social extensions

Bulk is a collection of per-recipient commands, not a new sender. Approval covers an immutable deduplicated recipient manifest, rendered content or frozen template/version/variables, schedule and estimated cost when known. Adding recipients/content invalidates approval. Suppression may remove recipients at dispatch without increasing scope. Pause/cancel affects unclaimed recipients; report in-flight and unknown separately.

Social drafts publish through the same command pipeline. Each destination is a separate command/result. Scheduled content edits require re-approval. Deletion/reaction is a state-changing operation with its own approval and capability; no automatic compensating delete.

## Moderation extension

Default disabled. When enabled, policy explicitly authorizes disclosure of minimized content to the configured model/provider. Identity block check always precedes model invocation. Structured output enum/score validation, versioned policy/model and strict timeouts are mandatory. Malformed/timeout response goes to review; it cannot authorize a send or block. Incoming content is untrusted data with no tool privileges. `recommend_block` opens a scoped human review; a confirmed block is a separate audited action. Blocked content never goes to normal AI.
