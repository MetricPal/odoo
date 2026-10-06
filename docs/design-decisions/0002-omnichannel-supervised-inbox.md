# ADR 0002 — Verified private-text intake and supervised inbox

Date: 2026-10-06. Status: accepted for the transport-neutral foundation. Supplements [ADR 0001](0001-omnichannel-governed-transport.md).

## Decision

Omni intake uses a fixed, endpoint-bound HTTP route and installed adapter verification. Core accepts only an immutable, bounded private-text event contract, queues it durably, and normalizes it in a separate database transaction under an explicitly activated processing policy. Human actions assign conversations, change work status, block identities and prepare replies. Replies use the existing immutable-command/Approval Center/worker path.

Activation is unavailable without an adapter declaring release readiness and passing read-only endpoint verification. No production adapter ships with this increment. Cron jobs and endpoints default to disabled. Policy activation authorizes text processing and the displayed retention periods only; it does not authorize contacts, business records, AI disclosure, attachments or sending.

## Scope and consistency

- The webhook route binds an existing endpoint to its company, team, account and immutable ownership version. A caller cannot supply a database/company/team selector. Production routing must still enforce a host-bound database filter, HTTPS and request limits at the proxy.
- Account plus event-key digest is unique. Account is a required precomputed stored relation, so the constraint holds on INSERT. Identical normalized events deduplicate; changed content with the same key is quarantined. Original normalized history is not rewritten.
- Identity rows are conservatively channel/team scoped, extending the foundation's purpose-scoped account decision. No cross-team identity join or automatic partner matching is performed. An operator may explicitly link an existing accessible contact; display/open actions recheck current contact permissions and company boundaries. Private conversations have one immutable identity; groups and participant expansion remain unsupported until a separate reviewed schema exists.
- A conversation is unique by endpoint/ownership version/thread. A message is unique within its conversation, with append-only numbered revisions. Older edits cannot replace newer content. Provider receipt events are restricted unresolved metadata pending a provider-specific reconciliation contract; no delivered/read status is inferred.
- Company-wide suppression requires a system administrator. Operators can confirm blocks within their team. The exact identity, scope and reason are displayed before confirmation. Unblock neither replays content nor grants consent.

## Concurrency boundary

Suppression and policy transitions use company → channel → command/event lock ordering. The company guard performs a no-value-change update of `res_company.write_date`; this creates a PostgreSQL row version without altering a business value or timestamp. Under Odoo's REPEATABLE READ isolation, an older concurrent snapshot must then serialize/retry instead of silently missing a committed block. A plain row lock would not provide that guarantee when the actual changes are in other tables.

Outbound claim/recovery selection takes the same company lock using SKIP LOCKED before channel/command locks. Inbound HTTP writes are safe for Odoo's transaction retry because they contain no external effects. All provider sends remain outside such retryable transactions. This conservative per-company serialization trades throughput for a clear suppression boundary; staging load tests are required before making capacity claims.

## Privacy and recovery

Invalid verification saves no payload. Newly blocked requests save keyed identity evidence and event metadata, without a body. A later block clears queued content unless a legal hold protects previously accepted evidence; held evidence remains manager-restricted, blocked from normalization/replay, and eligible for disposal after hold removal. A hold never permits retention of newly blocked content.

Successful normalization clears the pending payload. Policy retention redacts message bodies and every revision, and minimizes event metadata while retaining a deduplication tombstone. Tombstones prevent old content from reappearing. Full identity erasure, metadata disposal, backup erasure and restore certification are separate release gates.

Normalization uses savepoints: failure rolls back identities/conversations/messages from that attempt and preserves sanitized retry evidence. At five failures the event becomes a dead letter. A manager may replay retained recoverable events under the original policy/version; blocked, expired and collision events cannot be replayed.

## UX and security

Use native list/form/search views, company/team record restrictions, and server-side transition methods. Untrusted message bodies are plain text, not executable HTML. The inbox supports assignment to self, waiting/closed/reopen states, revision inspection and approved-reply preparation. It does not use chatter notifications or broadcast content over the bus. Refresh is currently manual; richer live updates and manager assignment to other operators remain follow-up UX work.
