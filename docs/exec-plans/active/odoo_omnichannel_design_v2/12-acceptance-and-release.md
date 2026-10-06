# Acceptance tests and release gates

No implementation or tests have run yet: this file specifies required evidence. Use a disposable Odoo/PostgreSQL database and mocked network by default. Never run provider sends in ordinary CI. Real tests require explicitly authorized sandbox accounts/recipients.

## Traceable test matrix

| ID | Scenario | Required evidence / expected behavior | Phase |
|---|---|---|---|
| T01 | duplicate company/purpose/type and archived duplicate | database constraint rejects; valid separate company succeeds | P0 |
| T02 | duplicate physical endpoint through second credentials/account | canonical physical key still rejected across purposes/companies | P0 |
| T03 | two independent transactions activate senders | one selected; failed health leaves previous selection; no lost-update activation | P0/P1 |
| T04 | no sender, unhealthy sender, incompatible reply | clear blocked reason; no transport call, no inactive-sender fallback | P1 |
| T05 | company/purpose isolation, combined roles, portal/public | read/search/group/export/RPC/bus/attachment and approval records do not leak | P0-P2 |
| T06 | direct send, forged approval, write/import of state/approvers | rejected server-side; no dispatch; requester cannot self-approve | P1 |
| T07 | content/recipient/media/policy/sender changes after approval | immutable revision or held invalidation; reapproval required | P1 |
| T08 | repeated approval execution and concurrent queue claims | exactly one durable command/attempt claim; existing result returned | P1 |
| T09 | crash before claim commit / after commit before send / after provider acceptance before result | no send for rolled-back claim; latter uncertain cases held, never blind resent | P1 |
| T10 | timeout/5xx/429/auth failure | adapter outcome classification, Retry-After, bounded retry/expiry; no duplicate known success | P1/P3 |
| T11 | stale worker and expired lease | token fencing protects results; expiration does not automatically resend | P1 |
| T12 | failed worker action rolls back | sanitized failure/attempt audit persists in controlled worker transaction | P1 |
| T13 | invalid/missing webhook auth, malformed/oversized body | reject without payload retention or business effects | P2/P3 |
| T14 | simultaneous duplicate events, changed payload with same key | one normalized effect; anomalous collision quarantined | P2 |
| T15 | unknown endpoint, disabled ingestion, stale ownership | quarantine/reject by contract; no contact/lead/AI/notification | P2 |
| T16 | purpose block, company block, expiry, unblock, new block after intake | isolation correct; block before normal objects/AI; no replay after unblock | P2 |
| T17 | raw/blocked payload retention, purge, legal hold | payload removed at policy deadline, metadata minimized, hold honored | P2 |
| T18 | out-of-order receipts and duplicate edits | state does not regress; no extra message for same revision | P2/P3 |
| T19 | permission/consent revoked after approval, concurrent cancel | no new claim; in-flight limitation visible and audited | P1/P3 |
| T20 | first adapter golden fixtures plus transport contract | sender/recipient/thread mapping, secret redaction, unsupported types fail closed | P3 |
| T21 | endpoint reassignment during receive/dispatch | history unchanged, old versions held; immutable until workflow ships | P2/P4 |
| T22 | attachment URL attacks, unsafe MIME, infected file, unauthorized download | blocked/quarantined, no SSRF or public data exposure | P4 |
| T23 | bulk changes, duplicate recipients, unsubscribe, partial cancellation | frozen scope; per-recipient results; only unclaimed work cancelled | P5 |
| T24 | moderation injection/timeout/malformed output/provider outage | review fallback; no automatic block/send; no external disclosure without policy | P7 |
| T25 | install/upgrade/uninstall safety, existing Approval Center regression | valid XML/access, historical integrity, no unrelated behavior change | each |
| T26 | keyboard/mobile/accessibility and native views | selected sender, disabled reason, approval status, unknown outcome understandable | each |
| T27 | performance, queue fairness, capacity limits and restore rehearsal | measured targets in file 11; documented hardware/results; restored system paused | live release |

Use Odoo TransactionCase/HttpCase and actual PostgreSQL constraints as appropriate; concurrency requires separate cursors/transactions, not a mocked sequential test. Frontend custom controls use the checkout's HOOT conventions. Static XML validation alone is not access or behavior testing. Assert outbound call count and persisted state at each failure injection point. Freeze time/randomness in backoff tests. Include malformed provider fixtures and fixtures with secrets to prove redaction.

## Coding gate (ready now)

- Canonical ownership, sender/reply policy, approval contract, queue boundaries, security defaults and phase scope are documented.
- Local Odoo 20 APIs and existing Approval Center inspected; implementation hardening explicitly scoped.
- Core/mock and first-adapter contracts are sufficient to start incremental implementation without real credentials.

## Foundation completion gate (not yet met)

T01-T19 as applicable, install/upgrade/security tests, code review, native UI walkthrough, documented audit/crash behavior. No unresolved high-impact authorization or duplication defect. All new invariants linked to test names in a completion report. Approval Center hardening is mandatory before any live transport.

## First live release gate (not yet met)

Authorized bot/account, secret provisioning, public HTTPS ingress and database routing, explicit ingestion/retention/service-response policy activation, distinct approver assignment, provider health and sandbox evidence, T20/T25-T27, backup/restore and alert runbook, designated operator. Outbound remains disabled until gates pass. No fabricated fixture-only claim of live support.

## Future adapter gate

Document exact API/version/product access/scopes, key namespace, webhook or polling transport, health semantics, recipient eligibility, content restrictions, quotas, consent and template rules, idempotency/reconciliation semantics and real sandbox evidence. Unsupported capability stays disabled. Broad catalog coverage is not a release criterion.

## Verification reporting

Report source revision, commands/test tags, disposable database identity, pass/fail counts, provider fixtures/live evidence, screenshots for UI changes, performance hardware, known limitations and migration behavior. No production configuration changes are implied by a successful test run.
