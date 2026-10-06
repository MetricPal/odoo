# Telegram release operations

## Isolated restore rehearsal — 2026-10-06

Source revision: `69d3afd6ae90`. Read-only ZIP backup with filestore from `omni_build_20261006`; native Odoo `odoo.modules.db.restore(..., copy=True, neutralize_database=True)` into previously nonexistent `omni_restore_rehearsal_20261006`, separate `/tmp/omni-restore-rehearsal-data`. No HTTP server, cron workers or provider secrets were started for the copy. Private backup stored outside the repository with mode 600.

Measured backup size 10,624,022 bytes; backup 1.731 seconds; restore 16.944 seconds. Assertions passed: dispatch disabled, no enabled endpoint, no active intake policy, no Telegram authorization, dispatch cron inactive, accepted command 314 and its single attempt/provider key preserved, no worker claim available. Source database and external webhook were unchanged. Sanitized result: `/tmp/omni-sandbox-runtime/restore-result.json`.

This is a local small-database recovery rehearsal, not a production RTO guarantee. RPO requires scheduled durable backups and off-host storage; neither exists yet. The private backup and restored copy contain sandbox conversation data and must follow the deployment owner's backup retention policy. They remain isolated for this certification work.

## Recommended deployment (not provisioned)

Dedicated Linux host; separate staging/production databases and processes; stable `hooks.<owned-domain>` hostname; named Cloudflare Tunnel and hardened webhook-only proxy; no public database manager or broad UI routes on the webhook hostname. A technical operator and backup operator own recovery and credentials; a distinct business approver authorizes messages. Administrator alerts should use a shared operations mailbox through an independently configured delivery path. Actual host/domain, named people, mailbox, retention and production activation require owner decisions.

The temporary Quick Tunnel is development infrastructure: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ . No infrastructure purchase, external alert or production activation is authorized by this recommendation alone.


## Local capacity and timeout characterization

Opt-in `omni_capacity` test on disposable `omni_regression_20261006`: **6,000 accepted requests in 599.982 seconds**, p95 **0.089656 seconds**, p99 **0.138727 seconds**. All 7,000 events ultimately normalized. Separately seeded 1,000-event admitted backlog: enqueue 23.554 seconds, drain **83.214 seconds**, below the 300-second target. One capacity test passed with zero failures/errors; log `/tmp/omni-capacity-final.log`.

Command: `PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server -c odoo.conf -d omni_regression_20261006 --data-dir=/tmp/omni-regression-data -u omni_telegram --test-enable --test-tags=omni_capacity --stop-after-init --http-port=8079 --max-cron-threads=0 --logfile=/tmp/omni-capacity-final.log`.

Hardware: Intel Core i5-8400, six logical CPUs, x86_64, approximately 15.4 GiB RAM; local PostgreSQL 16, Odoo 20, Python 3.12. Shared development host, including a separate regression run during the initial phase. This HttpCase uses a shared test transaction and synthetic transport, not production commit fsync/TLS/proxy/provider latency. Ingress and normalization were measured sequentially, not as concurrent sustained workers. The large test transaction made draining the initial 6,000-event set substantially slower than ingress. No production throughput guarantee follows; repeat the workload with real bounded worker commits and the chosen infrastructure before sizing or activating it.

The endpoint correctly enforces 600 events/minute. An initial test run was stopped to correct its burst fixture: the 1,000-event drain case must seed an already admitted backlog, not disable or exceed admission protection. The corrected full run passed; no production rate limit changed.

A real local socket-pair HTTP parser fault test with trickled headers terminated in **20.022 seconds**, within the 25-second transport budget. All eight standalone tools tests passed. No Telegram API call or external message occurred. This measures local timeout enforcement, not real DNS/TLS/provider availability.
