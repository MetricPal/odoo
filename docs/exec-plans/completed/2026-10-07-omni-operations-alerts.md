# Operations alerts through Odoo mail

Objective: shared, company/purpose-scoped channel monitoring using existing
`mail.mail` routing and outgoing servers. No separate SMTP credentials.

Scope: administrator-enabled per-channel policies, named internal recipients,
aggregate counters, change deduplication, recovery mail and native delivery status.
Disabled cron and policies on install; explicit Enable confirmation authorizes
one-minute monitoring and email queueing. No provider calls or live activation
in this implementation task. Infrastructure availability monitoring remains
external because Odoo cannot reliably report its own outage through its mail queue.

Implementation: extend the channel model and existing audit ledger, validate
administrator/team/company access at activation and each enqueue, freeze recipient
addresses, serialize collection with the channel lock, atomically queue mail and
persist counter fingerprint. Revoke by pausing; queued mail remains in Odoo's
queue and its delivery status is visible. Retain failed mail for native inspection,
without automatically resending uncertain outcomes. Neutralize policies on restore.

Validation: isolated database tests for disabled defaults, activation and RPC
bypass denial, company/purpose isolation, revoked recipients, initial healthy
silence, changed counters, deduplication, recovery and disabled/pause behavior;
actual native view loading. No SMTP send test against real infrastructure.

Rollback: pause policies and disable the monitoring cron; queued mail requires
separate administrator review/cancellation. Keep audit history.

## Implementation evidence

Implemented in `omni_channel` 20.0.1.4.0, shared by all providers. Native form
confirmation is browser-tested; eight targeted tests pass, and the combined
channel/Telegram regression passed 113 tests with no failures/errors. Final
policy audit includes recipient IDs and a scope/address/interval digest.
See `docs/references/odoo20-verification.md` for source verification and logs.

Implementation is complete. Live enablement and delivery/acknowledgement testing
remain deployment work; no production-readiness certification is implied.
