# Telegram release operations

## Isolated restore rehearsal — 2026-10-06

Source revision: `69d3afd6ae90`. Read-only ZIP backup with filestore from `omni_build_20261006`; native Odoo `odoo.modules.db.restore(..., copy=True, neutralize_database=True)` into previously nonexistent `omni_restore_rehearsal_20261006`, separate `/tmp/omni-restore-rehearsal-data`. No HTTP server, cron workers or provider secrets were started for the copy. Private backup stored outside the repository with mode 600.

Measured backup size 10,624,022 bytes; backup 1.731 seconds; restore 16.944 seconds. Assertions passed: dispatch disabled, no enabled endpoint, no active intake policy, no Telegram authorization, dispatch cron inactive, accepted command 314 and its single attempt/provider key preserved, no worker claim available. Source database and external webhook were unchanged. Sanitized result: `/tmp/omni-sandbox-runtime/restore-result.json`.

This is a local small-database recovery rehearsal, not a production RTO guarantee. RPO requires scheduled durable backups and off-host storage; neither exists yet. The private backup and restored copy contain sandbox conversation data and must follow the deployment owner's backup retention policy. They remain isolated for this certification work.

## Recommended deployment (not provisioned)

Update 2026-10-07: server ownership stays with the backend deployment.
Omni derives its HTTPS ingress hostname as `channels.[web.base.url hostname]`,
with no manual server/domain fields or URL preview. Endpoint
`_get_webhook_url()` supplies the registration URL; localhost/IP backends return
no public URL. DNS/TLS and provider registration remain separate deployment
steps. Reuse the existing Odoo mail transport for future alerts; per-channel recipient
routing and a disabled-by-default monitoring cron are now implemented in core
`20.0.1.4.0`. Actual activation, delivery and acknowledgement remain deployment
gates. See the core addon operations-alert runbook.

Dedicated Linux host; separate staging/production databases and processes; stable `channels.<backend-domain>` hostname; named Cloudflare Tunnel and hardened webhook-only proxy; no public database manager or broad UI routes on the webhook hostname. A technical operator and backup operator own recovery and credentials; a distinct business approver authorizes messages. Administrator alerts should use a shared operations mailbox through an independently configured delivery path. Actual host/domain, named people, mailbox, retention and production activation require owner decisions.

The temporary Quick Tunnel is development infrastructure: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ . No infrastructure purchase, external alert or production activation is authorized by this recommendation alone.


## Local capacity and timeout characterization

Opt-in `omni_capacity` test on disposable `omni_regression_20261006`: **6,000 accepted requests in 599.982 seconds**, p95 **0.089656 seconds**, p99 **0.138727 seconds**. All 7,000 events ultimately normalized. Separately seeded 1,000-event admitted backlog: enqueue 23.554 seconds, drain **83.214 seconds**, below the 300-second target. One capacity test passed with zero failures/errors; log `/tmp/omni-capacity-final.log`.

Command: `PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server -c odoo.conf -d omni_regression_20261006 --data-dir=/tmp/omni-regression-data -u omni_telegram --test-enable --test-tags=omni_capacity --stop-after-init --http-port=8079 --max-cron-threads=0 --logfile=/tmp/omni-capacity-final.log`.

Hardware: Intel Core i5-8400, six logical CPUs, x86_64, approximately 15.4 GiB RAM; local PostgreSQL 16, Odoo 20, Python 3.12. Shared development host, including a separate regression run during the initial phase. This HttpCase uses a shared test transaction and synthetic transport, not production commit fsync/TLS/proxy/provider latency. Ingress and normalization were measured sequentially, not as concurrent sustained workers. The large test transaction made draining the initial 6,000-event set substantially slower than ingress. No production throughput guarantee follows; repeat the workload with real bounded worker commits and the chosen infrastructure before sizing or activating it.

The endpoint correctly enforces 600 events/minute. An initial test run was stopped to correct its burst fixture: the 1,000-event drain case must seed an already admitted backlog, not disable or exceed admission protection. The corrected full run passed; no production rate limit changed.

A real local socket-pair HTTP parser fault test with trickled headers terminated in **20.022 seconds**, within the 25-second transport budget. All eight standalone tools tests passed. No Telegram API call or external message occurred. This measures local timeout enforcement, not real DNS/TLS/provider availability.

## Operations readiness

A restricted read-only collector is available at `addons/omni_telegram/tools/operations_status.py`. See the tools runbook for counters, severity mapping, operator response and recommended supervisor contract. ORM tests verify access denial to ordinary users, content-free output, no health/provider calls and critical reporting of unknown outcomes. Scheduling, mailbox routing, alert delivery/acknowledgement and named operator assignment remain pending deployment details. A recommendation is not an activated policy.

## Security and interface regression

Fresh install on disposable `omni_release_checks_20261006`, with no real provider transport, passed **103 tests, zero failures/errors**, using `-i omni_channel,omni_telegram --test-enable --test-tags=/omni_channel,/omni_telegram,-omni_capacity --stop-after-init --http-port=8081 --max-cron-threads=0`; log `/tmp/omni-release-checks.log`. Coverage includes company/purpose access, forbidden public/portal paths, immutable approvals, independent approvers, concurrent claims, crash/unknown fencing, retention/legal hold and native browser checks. The new 390×844 confirmation check verifies control names/focus and viewport fit; full screen-reader/manual keyboard navigation certification remains outside this automated check. Eleven Approval Center static checks and all eight standalone sandbox/deadline tests also passed.


Telegram's native HTML module description was verified through Odoo's `description_html` computation on the isolated restored database, removing the Markdown-as-RST fallback warnings. The desktop authorization screenshot was visually reviewed; its text preserves separate consent and per-message approval. No live sandbox dispatch or scheduler was activated during these release checks.

## Release decision: supervised sandbox only

| Step | Result | Remaining production gate |
|---|---|---|
| Restore isolation | Hooks and actual local backup/restore passed | Durable off-host backup schedule, retention, production-volume recovery/RPO evidence |
| Capacity and transport | Ten-minute local ingress, backlog and socket deadline checks passed | Real bounded commits, concurrent workers, TLS/proxy and provider quota on chosen staging host |
| Operations | Restricted collector and incident runbook implemented/tested | Named primary/backup operators, actual alert destination, approved schedule, delivery/acknowledgement test |
| Security and UI | Clean-install regression and targeted mobile/focus checks passed | Final deployment review, manual assistive-technology review; destructive core teardown needs retained backup/retention approval |
| Production activation | **Not performed** | Actual server/domain, credential provisioning, adopted policies and explicit reviewed activation approval |

The user requested Telegram completion and a stop before the next provider. Local implementation/evidence is committed in separate steps. Telegram remains a supervised private-text sandbox; production release is not certified. The stable server/domain, operator identities and shared alert mailbox have not been supplied or provisioned. Do not purchase infrastructure, change the existing webhook, send another message or activate recurring dispatch based on this report. No next-provider work has started.


## Shared Odoo mail alert implementation — 2026-10-07

Per-channel email policies now reuse native Odoo mail routing. The administrator
confirms automatic monitoring and delivery to authorized team members; no live
policy or scheduler was enabled during development. Read-only global diagnostics
remain separate from scope-filtered alerts. Runtime recipient/admin revocation,
change deduplication, recovery, pause and restore isolation are tested. Actual
mail delivery/acknowledgement and independent monitoring of Odoo outages remain
production gates; configured SMTP transport alone does not satisfy them.

## Alert mail pipeline evidence — 2026-10-07

The native Odoo queue-to-SMTP path now has loopback integration evidence:
alerts and recovery reach an in-memory SMTP sink and become `sent`; a 451 DATA
rejection becomes `exception`, stays visible, and does not cause repeat queueing
on unchanged counters. All 10 alert tests passed on the disposable database.
No external mailbox was contacted. Actual configured-server TLS/authentication,
mailbox receipt and operator acknowledgement remain production gates.


## Uninstall lifecycle rehearsal — 2026-10-07

Source before fix: `fd372623db03`. Disposable `omni_uninstall_20261007` was cloned
from the synthetic regression database, then seeded with an inactive Telegram
account/channel, one unknown command, an audit event and an unrelated generic
approval. Native `button_immediate_uninstall()` removed Telegram successfully.
The command remained unknown, account/audit and generic approval survived, and
adapter readiness was false after restart. Native core uninstall also completed;
`omni_command` and `omni_audit_event` tables were removed. The unrelated approval
survived and a new generic draft was created after removal. No external transport
or live configuration was involved. This characterizes destructive teardown; it
does not certify complete retention of Omni-linked approvals after core removal.

A second copy, `omni_adapter_uninstall_20261007`, reproduced readiness incorrectly
remaining true immediately after Telegram uninstall in the same process. The fix
registers adapter ownership and filters UI readiness by current-database module
state. Native install/uninstall then passed without restarting: ready after
installation, unavailable after removal, process factory retained. Two databases
in one process were also checked: installed stays ready, uninstalled stays unavailable.
See core decommissioning guidance; an actual active-webhook retirement was not tested.

## Alert transaction reliability — 2026-10-07

Independent PostgreSQL collector transactions now prove one durable queued alert
under contention, including a fresh-transaction retry after serialization failure.
Injected failures after queue creation and after snapshot flush leave no partial
mail/audit/snapshot state. All 13 combined alert checks passed, including native
loopback SMTP and confirmation UI. These strengthen local queue reliability;
real delivery/acknowledgement and external availability monitoring remain open.
