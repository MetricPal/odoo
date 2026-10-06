# Security, privacy and operations

These are project design defaults, not assertions of legal compliance. Deployment owners must adopt a retention/data-location policy before live activation.

## Authorization matrix

| Role | Allowed | Denied by default |
|---|---|---|
| Operator | read permitted conversations, prepare/submit, explicit block within authorized purpose | credentials, policy configuration, self-approval, direct dispatch |
| Approver | review full permitted command and approve/refuse under snapshotted policy | editing frozen content, expanding recipients, bypassing company/purpose access |
| Purpose manager | assignment, approved-policy configuration, scoped block/unblock, queue operations | other purposes without membership, credential disclosure |
| Provider administrator | configure account references, health, confirmed sender selection/webhook setup | automatic content visibility or approval solely from configuration role |
| Auditor | read sanitized authorized audit evidence | mutations and secrets |
| Worker | narrowly scoped private ingestion/dispatch under explicit company and policy | arbitrary model/action calls, broad AI tools |
| Portal/public | authenticated webhook transport path only through protocol verification | ORM/RPC model permissions, conversations, exports, bus subscription |

Company restriction uses Odoo 20 group-less `ir.access` CRUD domain `[('company_id', 'in', company_ids)]` on operational models plus purpose restrictions and grouped grants. No shared company-less operational records. A purpose domain must explicitly handle account/config models separately; do not force arbitrary purpose IDs onto global catalogs. Test multi-company users, combined roles and direct record IDs. Underlying CRM/HR record access is checked separately. UI counts, search, read_group, name display, notifications and attachments must obey the same boundaries.

## Secrets and transport

Initial resolver: opaque credential_reference maps to administrator-provisioned process secret/environment entry with strict prefix allowlist; never arbitrary file paths or arbitrary environment variable names. Secret values are never stored in Odoo fields, chatter, exports, errors or URLs shown to users. Provider URL paths containing tokens are redacted in HTTP logs. Deployment must protect process environment and supervisor access. A managed secret-store resolver can replace this interface without changing account records; mandatory external secret service is not required for core.

Record secret version/reference, not material. Rotation uses read-only identity verification before activation. No plaintext token widgets. OAuth adapters must add state/PKCE where appropriate, callback binding and narrowly scoped refresh-token storage before release; OAuth is not required for the first bot slice.

Provider hosts come from installed adapter allowlists. Reject private/link-local/loopback/metadata addresses, user-info URLs and non-HTTPS media URLs; revalidate redirects and resolved destinations and enforce network egress controls. Do not accept a generic fetch URL from a message. Media retrieval only through validated adapter references, bounded size and time. Quarantine before malware/type checks; no preview/download before clean. First live slice disables attachments entirely.

Webhook defaults: body limit 1 MiB, bounded parse depth/event count, per-account rate protection, verification before payload persistence, no secret-bearing body/header logging. Tune only after adapter review. Abuse counters may be aggregate metadata for invalid requests. No external health/AI calls inside webhook acknowledgement path.

## Blocks, consent and policies

“Global” block means all purposes within one company and channel identity namespace. UI calls it Company-wide. Database-wide cross-company blocking is unsupported. Block/unblock requires visible identity/scope/reason and explicit user confirmation; AI has recommendation-only permission. Unblock does not replay old blocked content or imply marketing consent.

Consent is operation/purpose/company-specific. Provider eligibility is not consent. First live slice permits approved responses to verified incoming private conversations under an activated service-response policy; unsolicited/promotional sending is disabled until explicit consent evidence is recorded and checked. Imports cannot grant consent without provenance. Bulk requires current suppression lookup immediately before each recipient claim; withdrawal cancels unclaimed work.

## Privacy and retention defaults

- Invalid requests: aggregate verification metrics only; no payload.
- Blocked requests: no content; keyed pseudonymous identity/event evidence for 30 days.
- Valid raw payloads: restricted, 7 days; quarantine also 7 days, then discard with count/reason. Clear payload sooner after successful normalization where troubleshooting policy permits.
- Conversation bodies/private attachments: 90 days by default, configurable before activation. No automatic sharing into email notifications.
- Command/audit metadata: 365 days by default; redact content and use references/hashes as appropriate. Expiry/erasure applies to backups through documented backup retention; legal hold is separately recorded.
- Secrets: no payload retention; rotation/revocation metadata only.

These periods are chosen operational defaults, not legal mandates. Retention changes require authorized confirmation and preview of impact. An activated policy authorizes bounded purge jobs; no silent new deletion policy. Audit records are append-only for application users, not falsely described as tamper-proof against a database administrator. Production can export signed/checkpointed audit batches to restricted external storage under a separately configured policy.

## Operational defaults and evidence

Metrics: ingress verification failures, dedup hits, unresolved/blocked events, inbox age, queue age, unknown outcomes, retries, per-account quota, health age, approval expiry, retention job failures. Do not put message bodies or identity labels in metric tags.

Structured logs carry correlation/command/event/attempt IDs, company/purpose and safe error codes. Alerts go to configured administrators only; no default external email/SMS. An account-level circuit breaker pauses sending after repeated qualifying failures; initial threshold 5 consecutive transport failures within 5 minutes, recheck after 5 minutes, never auto-select another sender. Clear business validation errors do not open a transport breaker.

Acceptance targets to measure, not claimed performance: webhook p95 < 1 second and p99 < 2 seconds under 10 events/second for 10 minutes with 1 MiB limit tested separately; 1,000-event burst drains within 5 minutes on documented staging hardware without external provider waits. Cron/worker throughput must be measured against deployment capacity before promising larger volume. Track oldest-job age rather than only averages.

Runbook:
1. Pause channel/account prevents new claims; show in-flight count and uncertainty.
2. Inspect sanitized attempts and provider evidence; reconcile unknowns without blind resend.
3. Renew credentials, perform health check, explicitly resume same sender; alternate sender requires selection workflow.
4. Replay inbox dead letters only after cause is fixed and authorization checked; preserve original key/version.
5. Database restore boots with ingress/dispatch disabled. Compare external accepted IDs and pending commands before resuming; backups cannot roll back external messages.
6. Initial recovery targets: RPO 15 minutes, RTO 4 hours for local records, subject to measured backup/restore rehearsal and infrastructure owner adoption. Not a promise to undo external actions.
7. Keep adapter API deprecation dates, last verified version, owner and sandbox evidence in release records. Revoked scopes fail closed.
