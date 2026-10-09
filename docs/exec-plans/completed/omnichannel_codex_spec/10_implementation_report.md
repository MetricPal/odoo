# Omni-Channel specification implementation

Implemented 2026-10-08 in `omni_channel` 20.0.1.7.0, preserving existing workspace
changes and the provider-independent runtime.

## Delivered behavior

| Specification | Implementation and evidence |
| --- | --- |
| Navigation | Overview, Inbox, Messages, Channels, Monitoring, Configuration. Exact menu trees asserted by setup and operations tests. |
| First entry | Scoped welcome, specified headline/description, Add Channel and six-step progress; browser test covers administrators with no visible channels. |
| Generic wizard | Data-driven channel catalog with Messaging/Social/Other categories and adapter availability. Separate Channel, Connection, Inbound, Outbound, Verify, Activate steps; scoped configuration dialogs preserve the wizard. |
| Activation | Rechecks health rather than trusting wizard state. Existing public sender activation and endpoint enable methods enforce access, checks and policy. Returns to channel detail. Outbound dispatch authorization remains separate. |
| Channel detail | Identity/status, selected sender, endpoint count and connection/inbound summaries; Outbound Senders, Inbound Endpoints, Operations and Alerts sections. |
| Senders | Existing radio selection, per-scope uniqueness, generation fencing and atomic switching retained. Failed verification leaves the previous sender selected. |
| Inbound | Multiple endpoints, explicit purpose and receiving identity, health and last-check time. Verification alone does not enable intake. Existing unique physical identity and immutable ownership constraints retained. |
| Blocklist | Configuration → Blocklist; channel-type/purpose/account-identity scope, optional system-admin-only company-wide scope, reason, expiry, actor and timestamp. Existing checks precede identity/conversation/business processing and repeat at normalization. |
| Messages | Operational message list with sender and creation time, purpose and related conversation; retry/provider/lease fields and attempt history collapse under Technical Details. Existing approval workflow remains available. |
| Overview | Scoped channel health, connection warnings, inbound enabled counts, attention messages, delivery issue count/action and recent audit activity; no permanent setup guide once channels exist. |
| Monitoring | Health, Delivery, Failed Messages, Activity / Logs. |
| Technical administration | Settings → Technical → Omni-Channel contains catalog, teams, recipient authorization and intake event diagnostics. Existing low-level models are preserved. |
| Providers | Catalog-wide mocked setup and activation exercise the same generic architecture. Unsupported adapters fail closed. Existing Telegram sandbox remains a separate adapter, not the core conceptual model. |

Routing uses the existing endpoint-to-purpose binding, not a duplicated routing
engine. Email/SMS remain native Odoo services. Hermes Agent was not changed.

## Authorization and secrets

Wizard entry/configuration require the existing Omni administrator role and
selected-company/purpose access. Overview searches retain record rules and never
sudo across scopes. Public methods revalidate permissions. Opening screens and
running health checks never authorize dispatch. Receiving requires an explicitly
activated policy; wizard Activate has a confirmation explaining its effect.
Sender selection, block/unblock, recipient authorization, alert policies and
message approval retain their existing independent controls and audit trails.

Credentials remain deployment-provisioned secret references; token values are
never stored in the wizard or returned by health errors. Endpoint health fields
are server-managed, with create/write guards and sanitized audit text.

## Verification

Odoo 20 local source: commit `026b3ed9bfbc91a67e80755d755ca8fc83fddb88`,
`odoo/release.py`, native menu definitions, radio widget, transient actions,
existing runtime/approval methods and ORM tests. See the version-verification log.

Disposable PostgreSQL 16 cluster: `/tmp/omni-spec-pg`, port 55432.
Database: `omni_spec_test`; filestore: `/tmp/omni-spec-data`.

- Fresh module installation and targeted setup/foundation/inbox: **49 tests,
  zero failures/errors** (`/tmp/omni-spec-test2.log`).
- Backend plus initial browser verification: **34 tests, zero failures/errors**
  (`/tmp/omni-spec-ui.log`).
- Full module regression, including browser, authorization, concurrency,
  transactions, inbound blocking, dispatch and Telegram sandbox: **145 tests,
  zero failures/errors** (`/tmp/omni-spec-final.log`). Capacity benchmark excluded.
- Final catalog migration, scoped setup and browser verification: **15 tests,
  zero failures/errors** (`/tmp/omni-spec-visual-final.log`).
- Clean final installation in `omni_spec_fresh`: **8 setup tests, zero
  failures/errors** (`/tmp/omni-spec-fresh.log`).
- Ruff passes for changed core models and setup tests; unstaged diff whitespace
  check passes. The supplied staged specification has an existing trailing-space
  warning in `01_information_architecture.md`.
- Chrome screenshots reviewed for welcome, generic wizard, Overview cards and
  technical-details behavior. Visual review corrected dashboard overflow and
  verified the primary navigation remains visible.

Upgrade testing caught protected catalog records and XML search returning only
one ID; category seeding now uses a native nested recordset search/write and
preserves already configured categories. Both fresh install and upgrade tests
cover the built-in categories.

Full regression command:

```sh
PYTHONPATH=/tmp/omni-spec-deps .venv/bin/python odoo-bin \
  -d omni_spec_test --db_host=/tmp --db_port=55432 --db_user=moshkou \
  --addons-path=addons -u omni_channel,omni_telegram --test-enable \
  --test-tags=/omni_channel,/omni_telegram,-omni_capacity \
  --stop-after-init --http-port=8079 --max-cron-threads=0 \
  --data-dir=/tmp/omni-spec-data --logfile=/tmp/omni-spec-final.log
```

Final focused command uses the same options with
`--test-tags=/omni_channel:TestOmniSetup,/omni_channel:TestOmniUI` and
`--logfile=/tmp/omni-spec-visual-final.log`.

## Deployment boundary

No real provider account, webhook, business database, outbound send, or live
policy was activated. The existing deployment still requires a separately
approved module upgrade. Catalog-wide tests use mock adapters; this work does
not implement or certify production WhatsApp/Slack/social providers. Health
summaries report configuration/last verification, not continuous provider uptime.
