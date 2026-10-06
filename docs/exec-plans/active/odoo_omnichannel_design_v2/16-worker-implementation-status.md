# Outbound worker implementation — 2026-10-06

Addon: `addons/omni_channel`, version `20.0.1.1.0`. This increment adds the transport-neutral dispatch lifecycle to the [configuration foundation](15-implementation-status.md). It does not enable production messaging or complete P1/P2/P3.

## Delivered behavior

- A disabled cron uses independent Odoo registry cursors to claim, commit, invoke transport outside a database transaction, and persist results in a separate transaction. HTTP and approval actions only prepare or queue work.
- PostgreSQL channel/command locks use `FOR UPDATE SKIP LOCKED`. Lock ordering is channel, command, attempt. A channel permits one in-flight attempt and no new claims while an outcome is unknown. Rolled-back claims never invoke transport.
- Each claim verifies the frozen payload and sender generation, current configuration and requester access, exact linked approval and required approvers, policy fingerprint, expiry, and current recipient authorization evidence.
- Recipient authorization is explicit, scoped to channel/namespace/recipient, expiring, manager-confirmed and revocable. Confirmed/revoked evidence is immutable. It is a manual evidence record, not automatic proof of consent or a substitute for future provider-specific recipient eligibility and blocklist checks.
- The committed immutable claim contains the exact original payload and opaque credential reference, never an ORM record or resolved secret. Read-only provider preflight rechecks sender identity and command eligibility before one transport invocation. No production adapter is included.
- Attempts have unique numbers and lease tokens. Completion is fenced against both command and attempt identity; late/duplicate results cannot overwrite final evidence. A 120-second expired lease becomes unknown, even if the process might have failed before sending.
- Only a definite no-send result marked retryable is retried. There are at most five attempts, with approval-expiry bounds, exponential full jitter (one-second floor, 900-second cap) and provider Retry-After. Unknown outcomes never retry automatically. Accepted means provider acceptance, not recipient delivery.
- Per-channel persistent throttling uses a configurable 1–3600 second minimum interval (default one second). Retry-After applies to the whole channel. Five transport, unhealthy or unauthorized failures within five minutes open a five-minute circuit. No automatic sender failover occurs.
- Pause and recipient revocation serialize against claims. The durable claim is the authorization cutoff: a later pause/revocation cannot recall an in-flight request. Every future retry rechecks authorization.
- In-flight/unknown commands prevent sender changes and local cancellation. A manager can reconcile an unknown outcome using explicit provider evidence and, for acceptance, a provider message ID. Verified not-sent closes as failed; replacement requires fresh preparation and approval. Original uncertain attempts remain unchanged.
- Native forms expose recipient evidence, pause controls, attempt history and reconciliation. Worker state, attempt evidence and lease identity are protected against client writes/default context. Company/team restrictions apply to the new records.

## Odoo 20 verification and scope decisions

Implementation uses the actual checkout's `odoo/orm/registry.py` cursor API and existing Odoo 20 cron model. The scheduler wrapper owns transaction boundaries; model helpers never commit a caller's transaction. Private worker methods require a superuser environment and are not public RPC actions. The cron's job/time bounds are 10 claims and a 45-second loop deadline, capped at 50 claims per invocation. This deadline cannot interrupt an adapter already executing.

Accounts remain purpose- and company-scoped, with one channel per scope/type. The conservative channel throttle is sufficient for this foundation's account ownership shape; account sharing, distributed provider quotas and platform-specific throttles require further design before broader adapters.

No scheduler or channel is enabled, and there is deliberately no public enable/resume action yet. Future activation must validate adapter readiness and the explicit automation policy. Merely toggling a cron must not grant transport authorization.

## Verification evidence

Disposable database: `omni_build_20261006`; data: `/tmp/omni-build-data`. No production database was upgraded and no provider request was made.

Full suite command:

```sh
PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_build_20261006 --data-dir=/tmp/omni-build-data \
  -u omni_channel --test-enable --test-tags=/omni_channel --stop-after-init \
  --http-port=8077 --max-cron-threads=0 --logfile=/tmp/omni-worker-release-test.log
```

Result: 50 tests, zero failures/errors, including real headless Chrome and independent PostgreSQL sessions. The 18 new model tests cover acceptance, timeout/malformed results, authorization withdrawal/expiry, retry/circuit budgets, lease recovery, fencing, reconciliation, permission boundaries and disabled defaults.

Three independent-transaction tests verify durable attempt visibility from the mock transport, one invocation across repeated worker runs, result-persistence failure followed by unknown recovery without resend, competing claims skipping a locked channel, and rollback releasing work without leaving an attempt. These transaction tests stub authorization to isolate transaction behavior; the model tests exercise the actual approval and recipient checks.

The initial recovery test found a missing ORM flush before raw SQL, now fixed. The independent crash fixture also caught a test timezone assumption; it now uses Odoo's UTC datetime value instead of a PostgreSQL session-local timestamp.

A subsequent targeted browser run passed both tests (zero failures/errors), verifying the new unknown-outcome reconciliation modal, its evidence field, explicit confirmation, no-resend explanation and absence of cancellation. See `/tmp/omni-worker-ui-test.log` for its result. Together these runs cover 51 distinct tests. A dedicated app-description HTML file also removes the earlier Markdown-as-reStructuredText rendering warnings. Native XML is loaded through the module upgrade. Ruff and all 11 existing Approval Center static tests pass.

## Remaining release gates and next slice

1. Implement P2 verified ingress, normalized conversations/identities, blocklist enforcement and the supervised inbox. No webhook controller or automatic business-record creation is provided here.
2. Implement isolated Telegram private-text transport with credential resolution, bounded HTTP connect/read timeouts (adapter contract: at most 5/20 seconds), provider-specific eligibility/consent rules, response classification and sandbox certification. The core has no hard interruption mechanism for a hung third-party adapter; bounded I/O must be proven before enabling one.
3. Move sender-activation network preflight outside the configuration lock and recheck versions under lock. Dispatch preflight is already outside locks; activation still has the foundation limitation.
4. Add governed activation/resume and provider capability checks; certify worker deployment/concurrency and operational monitoring under realistic load. No provider callback receipt reconciliation, delivery/read status, automatic uncertain replay or throughput certification is claimed.
5. Complete the remaining acceptance matrix: live end-to-end transport, inbox, attachments, retention, mobile and external API behavior remain pending. Existing audit records are append-only through ORM, not tamper-proof against database administrators.
