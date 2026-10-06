# Omni-Channel

Odoo 20 Community foundation for company- and purpose-scoped communication.

## Available in 20.0.1.0.0

- Native channel kanban/list/forms and a deliberate app icon.
- Twelve channel catalog entries, explicitly marked unavailable without an installed adapter.
- Company/purpose ownership, connection references, outbound sender configurations and inbound endpoint configuration.
- Radio selection of one runtime sender, verified health, stale-selection protection, database uniqueness and explicit deactivation.
- Prepared messages with immutable submission snapshots, distinct assigned approvers, expiry, refusal/cancellation and idempotent local enqueue.
- Scoped integration with the existing Approval Center; ordinary requests retain their existing behavior.
- Append-only application audit, secret-reference field restrictions and server-side RPC/default-context protections.

## Operational boundary

This is a foundation release. No production provider adapter, webhook controller, inbox processor or outbound worker is installed. Endpoint intake remains Not enabled. Queued means retained locally, not sent. No cron, external sending, automatic policy activation or demonstration connections are installed. Healthy providers in automated tests are mocks only.

The existing production database was not upgraded. Installation and tests used `omni_build_20261006` with data under `/tmp/omni-build-data`.

## Configure access

1. In Settings, a system administrator grants Omni-Channel Administrator to configuration owners and Operator to reviewers/requesters as appropriate.
2. A system administrator assigns internal users to Communication Teams. A role alone does not grant purpose membership; selected Odoo companies also restrict access.
3. Configure one channel for the company, business purpose and channel type. Configure connections under that same scope. Credential fields accept only `OMNI_SECRET_...` references, never token values.
4. Configure sender identities and inbound endpoint identities. An unavailable adapter cannot pass Check & Activate. Do not enter invented health evidence to work around this.
5. For future provider-enabled preparation, select a company-specific Approval Center type with explicit approvers. Each must have the Approval Center Approver role, the communication team, company access and be different from the requester. Manager-derived chains are intentionally rejected in this first integration.

A failed health check preserves the previous runtime sender. Switching or deactivating the sender holds pending/approved/queued messages. Duplicate a held message to obtain a fresh review. Activated ownership cannot silently move to another company or purpose.

## Verification

Run against a disposable database, never a real organizational database:

```sh
python odoo-bin server -c odoo.conf -d YOUR_DISPOSABLE_TEST_DB \
  --data-dir=/tmp/omni-test-data -i omni_channel --without-demo=all \
  --test-enable --test-tags=/omni_channel --stop-after-init \
  --http-port=8077 --max-cron-threads=0
```

Use `-u omni_channel` for the upgrade path. Browser tests require Chrome and `websocket-client`; a skipped browser test is not a pass. The concurrency test deliberately uses independent PostgreSQL transactions and removes its committed fixture. All other fixtures roll back. Tests perform no real provider requests.

See the [implementation report](../../docs/exec-plans/active/odoo_omnichannel_design_v2/15-implementation-status.md) for exact verification commands and remaining work.
