# Implementation sequence and deliverables

No phase is complete based only on a successful install. Each passes the applicable [acceptance gates](12-acceptance-and-release.md).

## P0 — Foundation contracts

Implement ownership/catalog models, Odoo 20 access restrictions, indexes, identity normalization, adapter DTOs, mock adapter and native configuration screens. No external provider requests. Test company/purpose isolation, duplicate physical endpoints and concurrent selection.

## P1 — Governed command execution

Implement immutable commands, scoped Approval Center hardening, policy snapshots, outbox, attempts, worker claiming, uncertain outcomes, dispatch health checks and audit persistence. Native review/queue/health UI is part of this phase. All tests use mock transport. Exit requires approval bypass and crash-point tests.

## P2 — Safe inbound

Implement signed/secret verification contract, durable inbox, endpoint ownership resolution, blocklist, quarantine, replay/dedup, private conversation UI and activated ingestion policy. Block/unblock is human-confirmed and audited. AI interface is a disabled optional hook, not a fabricated moderation engine.

## P3 — First live Telegram slice

Optional adapter for private text updates and approved text sends/replies. Verify actual bot identity and secret reference, configure webhook only through explicit confirmed action, demonstrate duplicate webhook and ambiguous-send recovery using a sandbox bot and authorized recipients. No bulk, groups, media, paid messages or social operations. Production gate needs credentials and deployment checklist; mock success is insufficient.

## P4 — Media and business bridges

Private ir.attachment integration, safe retrieval/scanning, existing-record linking, then approved deterministic CRM/Recruitment effects. Add consent management before promotional/bulk use. Implement endpoint reassignment workflow; until then server rejects reassignment of activated endpoints.

## P5 — Additional messaging and bulk

Provider-specific research and contract fixtures before WhatsApp, Slack or Discord activation. Bulk uses immutable audience/content snapshots, per-recipient commands, current suppression, quota-aware scheduling, cancellation and partial-result UI. Account approval/API access is a release gate for each adapter.

## P6 — Social publishing

One adapter/operation family per reviewed increment. Separate post drafts, previews, schedules, template versions and per-destination commands. Re-approval after material edits; unsupported features remain unavailable.

## P7 — Optional moderation and analytics

Versioned moderation provider, consent/data-disclosure policy, structured-output validation, injection tests, human review and block recommendations. Analytics uses company/purpose-filtered facts and documented denominators. It never becomes an authorization source.

## Rollout

Use disposable databases for automated tests; migration/upgrade tests precede staging. Launch a single purpose/account with small controlled volume; verify operations runbook and restore behavior. Expand only after measured acceptance. Database restore starts with ingress and dispatch disabled until external outcomes and offsets are reconciled.
