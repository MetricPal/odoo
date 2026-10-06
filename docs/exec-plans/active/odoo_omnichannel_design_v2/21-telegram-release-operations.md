# Telegram release operations

## Isolated restore rehearsal — 2026-10-06

Source revision: `69d3afd6ae90`. Read-only ZIP backup with filestore from `omni_build_20261006`; native Odoo `odoo.modules.db.restore(..., copy=True, neutralize_database=True)` into previously nonexistent `omni_restore_rehearsal_20261006`, separate `/tmp/omni-restore-rehearsal-data`. No HTTP server, cron workers or provider secrets were started for the copy. Private backup stored outside the repository with mode 600.

Measured backup size 10,624,022 bytes; backup 1.731 seconds; restore 16.944 seconds. Assertions passed: dispatch disabled, no enabled endpoint, no active intake policy, no Telegram authorization, dispatch cron inactive, accepted command 314 and its single attempt/provider key preserved, no worker claim available. Source database and external webhook were unchanged. Sanitized result: `/tmp/omni-sandbox-runtime/restore-result.json`.

This is a local small-database recovery rehearsal, not a production RTO guarantee. RPO requires scheduled durable backups and off-host storage; neither exists yet. The private backup and restored copy contain sandbox conversation data and must follow the deployment owner's backup retention policy. They remain isolated for this certification work.

## Recommended deployment (not provisioned)

Dedicated Linux host; separate staging/production databases and processes; stable `hooks.<owned-domain>` hostname; named Cloudflare Tunnel and hardened webhook-only proxy; no public database manager or broad UI routes on the webhook hostname. A technical operator and backup operator own recovery and credentials; a distinct business approver authorizes messages. Administrator alerts should use a shared operations mailbox through an independently configured delivery path. Actual host/domain, named people, mailbox, retention and production activation require owner decisions.

The temporary Quick Tunnel is development infrastructure: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ . No infrastructure purchase, external alert or production activation is authorized by this recommendation alone.
