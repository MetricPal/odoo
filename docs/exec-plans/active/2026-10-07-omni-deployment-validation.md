# Deployment validation: sequential milestones

User direction: complete the next planned milestones one by one and commit each.
This follows P3 rollout and the T25/T27 release gates; it does not start P4/P5.

1. Install on the configured local `odoo20` target, after a private database and
   filestore backup and installation rehearsal on a neutralized copy. Verify
   existing approvals/business records, module versions and disabled defaults.
   Do not assign users or enable integration policies in this milestone.
2. Configure governance after the user identifies primary/backup operators and
   alert recipients. Record exact role, company and purpose scope before changes.
3. Verify actual alert delivery/acknowledgement using reviewed recipients and
   message scope. Local SMTP tests do not replace this gate.
4. Complete deployment-specific HTTPS/DNS, backup retention/off-host storage and
   recovery checks before any separately approved Telegram production activation.
5. Resume original P4 media/business-bridge development after deployment work is
   complete or explicitly deferred; additional providers belong to P5.

## Milestone 1 scope and rollback

Existing configuration identifies `odoo20`, local PostgreSQL and loopback Odoo
base URL. Preserve current mail settings and user access. New modules may be
installed, but their dispatch/intake/alert controls and crons must stay disabled.
No provider credentials, webhook registration, scheduler or external message.

Back up database plus filestore outside Git with private permissions. Rehearse
native restore with `copy=True, neutralize_database=True`; neutralization changes
only the copy. Verify installation and compare counts/identity/state of existing
approval and business records. Then install only the two requested modules on
the target with HTTP/cron workers disabled. Record checks and commit evidence.

Rollback is restoration from the pre-install backup during an approved outage,
not core uninstall: core uninstall deletes its history. Backup contains real
organizational data and credentials; it remains local/private and must later be
moved into the owner's approved retention/storage process. No backups committed.

## Milestone 1 completed — 2026-10-07

- Native database-plus-filestore backup created privately outside Git at
  `/tmp/omni-deployment-20261007/odoo20-before-omni.zip` (49,438,844 bytes,
  directory mode 0700, archive mode 0600). Backup took 7.3 seconds; native restore
  into the neutralized rehearsal database took 43.0 seconds. This temporary
  local archive is not an off-host backup or a completed retention arrangement.
- Installed on the restored copy with the target's full 147-module app mix.
  Combined Omni-Channel/Telegram suite: **120 tests, zero failures/errors**.
  Capacity tests were excluded. Provider network was disabled; SMTP tests used
  the loopback sink. The suite did not run against the main database.
- Installed `omni_channel` **20.0.1.4.1** and `omni_telegram` **20.0.1.0.1** on
  configured local `odoo20`, with HTTP and cron workers disabled. No other
  database sessions were present before installation. Both modules report
  `installed`; native registry initialization completed successfully.
- Compared counts and sorted row fingerprints across ten existing approval,
  business, user/company/access and mail tables before/after installation and
  after rehearsal tests. Original business values were preserved. The explicit
  exception is `approval_center_request.write_uid/write_date`: Odoo stamps these
  while initializing the new stored computed purpose field. Rehearsal verified
  that all other original approval fields were unchanged. Mail configuration,
  queued mail and group memberships matched their original values exactly.
- All four Omni crons remain inactive. No channels, accounts, senders, endpoints,
  intake policies, commands or purpose-team assignments exist on the target.
  No live email was sent, no provider webhook was registered, and no integration
  activation or user-role assignment was performed.
- Backend base URL remains `http://localhost:8069`; a public webhook cannot yet
  be derived. Shared backend-derived `channels.[domain]` behavior remains the
  rule for all providers, without manual per-channel hostname/domain fields.

Private logs, comparison metadata and the installation verification report are
under `/tmp/omni-deployment-20261007/`. They are not committed because the backup
and adjacent evidence relate to organizational data. This commit records the
local installation evidence; installation itself is database state, not Git state.

## Next: milestone 2 — named governance assignments

Awaiting the user's names/login emails for primary operator, backup operator and
alert recipients. Confirm their company and communication-purpose scope before
assigning access. Existing SMTP configuration supplies mail transport, not an
implicitly approved recipient. No further activation is authorized by the
installation milestone. Milestones 3–5 remain pending as listed above.
