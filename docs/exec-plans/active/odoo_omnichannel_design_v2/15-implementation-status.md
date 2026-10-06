# Implementation status — 2026-10-06

Addon: `addons/omni_channel`, version `20.0.1.0.0`.
Status: configuration foundation and governed message preparation implemented. This is not a production messaging release, and P1/P2/P3 are not complete.

## Implemented

- Company/purpose/channel uniqueness including archived configurations.
- Canonical-key connection/sender/endpoint configuration, required ownership alignment and protected derived scope.
- Multiple sender configurations, partial unique selected-sender index, serialized activation/deactivation, verified identity comparison and stale dialog generation check.
- Native channel cards, configuration lists/forms, radio selection dialog, prepared-message review screens and a deliberate SVG app icon.
- Role grants AND company/purpose restrictions. Team membership is system-administrator controlled; ordinary provider administrators cannot grant themselves membership. Credential-reference fields are restricted to configuration administrators.
- Server-guarded health, selection, command evidence and immutable audit records; caller-provided `default_*` context cannot bypass these guards.
- Frozen command payload/hash, expiry, snapshotted policy/approver evidence and exact sender generation. Prepared message uses existing Approval Center, with separate-assigned-user review, required/ordered approvers, refusal, cancellation and one-shot local enqueue.
- Pending work is held on sender switch. Original generic Approval Center requests remain supported and have regression coverage.

## Explicitly not implemented yet

- Production provider adapters and actual credential resolution/HTTP transport.
- Outbound worker, attempts/leases, receipt reconciliation, rate control, safe retries, unknown outcome handling and dispatch consent enforcement. The local queued state is not a delivery claim.
- Verified webhook ingestion, normalized conversations/identities, blocklist, moderation, attachments, retention jobs and business bridges.
- Live Telegram, other messaging providers, bulk and social operations.

No real connection or automation policy is activated. Endpoint state remains Not enabled. A mock healthy adapter exists only inside tests. Do not enable real adapters until the worker, policy and ingestion release gates are implemented and tested.

## Implementation decisions and constraints

1. Foundation accounts are purpose-scoped in addition to company-scoped, making early access boundaries conservative. Sharing a connection across business purposes will need a reviewed change if required later.
2. Health check and sender selection currently run under the channel lock. There is no network adapter in this increment. Before live adapters, implement the planned bounded external preflight and locked version recheck, plus dispatch/unknown guards; do not let network requests hold configuration locks indefinitely.
3. Audit is append-only at the ORM application boundary, not tamper-proof against database administrators. This release has no destructive retention job.
4. Approval Center requests and related records have explicit no-Omni branches in their restriction domains. Category approver lines have no request; they must remain visible to the existing approval flow. A regression test caught and verified this boundary.
5. All operational sender/endpoint scope fields use precomputed stored relations. This checkout requires precomputation for required ownership values to exist during INSERT.
6. Native Odoo radio selection avoids unnecessary custom JavaScript. The browser test verifies the actual rendered modal and its confirmation copy.

## Test evidence

Separate database: `omni_build_20261006`; filestore `/tmp/omni-build-data`. Existing ERP database unchanged. Initial installation and subsequent upgrades succeeded.

Runtime: `/home/moshkou/workspace/odoo/odoo-venv/bin/python`. Temporary test-only dependencies `websocket-client 1.9.2` and `ruff 0.16.10` were installed under `/tmp/omni-test-deps`, without modifying the project virtual environment.

Full database/browser/concurrency suite:

```sh
PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_build_20261006 --data-dir=/tmp/omni-build-data \
  -u omni_channel --test-enable --test-tags=/omni_channel --stop-after-init \
  --http-port=8077 --max-cron-threads=0 --logfile=/tmp/omni-release-test.log
```

Result: 29 tests, zero failures/errors. Includes actual headless Chrome navigation and two independent PostgreSQL sessions contending on the selected-sender unique index. Expected constraint violations are asserted by tests; their SQL log entries are not suite failures.

Additional validation:

```sh
/tmp/omni-test-deps/bin/ruff check addons/omni_channel
/home/moshkou/workspace/odoo/odoo-venv/bin/python addons/approval_center/tests/test_approval_center_static.py
```

Ruff passed. All 11 existing Approval Center static tests passed. Native XML loaded during installation/upgrade, not merely parsed. Screenshots from the browser test were visually inspected: channel cards and sender selection.

## Remaining acceptance evidence

This increment covers the configuration portions of T01-T08, T19 and T25-T26 and the selected-sender database concurrency invariant. It does not claim complete coverage of those end-to-end scenarios. T09-T18 transport/inbox behavior and later-phase gates remain pending. Mobile, external API and recovery/performance certification remain pending.

## Next implementation slice

Complete P1 transport-neutral worker with persisted attempts, crash-point tests, unknown outcomes and current authorization/consent checks before adding live sending. Then P2 verified inbox/blocklist/conversation workflow, followed by the isolated Telegram adapter and its sandbox gate. Preserve the current unavailable/disabled UI until each capability is genuinely executable.
