# Omni-Channel

Odoo 20 Community foundation for company- and purpose-scoped communication.

## Available in 20.0.1.4.1

- Native channel kanban/list/forms and a deliberate app icon.
- Twelve channel catalog entries, explicitly marked unavailable without an installed adapter.
- Company/purpose ownership, connection references, outbound sender configurations and inbound endpoint configuration.
- Radio selection of one runtime sender, verified health, stale-selection protection, database uniqueness and explicit deactivation.
- Prepared messages with immutable submission snapshots, distinct assigned approvers, expiry, refusal/cancellation and idempotent local enqueue.
- Scoped integration with the existing Approval Center; ordinary requests retain their existing behavior.
- Append-only application audit, secret-reference field restrictions and server-side RPC/default-context protections.

- Persisted dispatch attempts, fenced leases, current approval/recipient checks, throttling, bounded safe retries and recovery to unknown outcomes.
- Recipient authorization records, pause controls, read-only attempt history and evidence-based manual reconciliation.

## Operational boundary

This is a foundation release with a transport-neutral outbound worker. Its cron and each channel ship disabled; core alone exposes no public enable action. The optional `omni_telegram` addon adds explicitly authorized sandbox reply activation. Verified webhook handling and a private-text inbox processor are installed. Core includes no production adapter or credential resolver; the optional [Telegram sandbox addon](../omni_telegram/README.md) provides a scoped resolver and bounded private-text transport, with live certification still pending. Endpoint intake and the inbox/retention cron jobs default to disabled; activation requires a release-ready adapter and explicit processing policy. Queued means retained locally. Accepted means the provider acknowledged the send, not that the recipient received it. Automated tests use mocks only.

The existing production database was not upgraded. Installation and tests used `omni_build_20261006` with data under `/tmp/omni-build-data`.

## Configure access

1. In Settings, a system administrator grants Omni-Channel Administrator to configuration owners and Operator to reviewers/requesters as appropriate.
2. A system administrator assigns internal users to Communication Teams. A role alone does not grant purpose membership; selected Odoo companies also restrict access.
3. Configure one channel for the company, business purpose and channel type. Configure connections under that same scope. Credential fields accept only `OMNI_SECRET_...` references, never token values.
4. Configure sender identities and inbound endpoint identities. An unavailable adapter cannot pass Check & Activate. Do not enter invented health evidence to work around this.
5. For future provider-enabled preparation, select a company-specific Approval Center type with explicit approvers. Each must have the Approval Center Approver role, the communication team, company access and be different from the requester. Manager-derived chains are intentionally rejected in this first integration.

A failed health check preserves the previous runtime sender. Switching or deactivating the sender holds pending/approved/queued messages. Duplicate a held message to obtain a fresh review. In-flight and unknown sends block sender switching and cannot be cancelled locally. Activated ownership cannot silently move to another company or purpose.

## Verification

Run against a disposable database, never a real organizational database:

```sh
python odoo-bin server -c odoo.conf -d YOUR_DISPOSABLE_TEST_DB \
  --data-dir=/tmp/omni-test-data -i omni_channel --without-demo=all \
  --test-enable --test-tags=/omni_channel --stop-after-init \
  --http-port=8077 --max-cron-threads=0
```

Use `-u omni_channel` for the upgrade path. Browser tests require Chrome and `websocket-client`; a skipped browser test is not a pass. Concurrency and crash tests deliberately use independent PostgreSQL transactions and remove their committed fixtures. Other fixtures roll back. Tests perform no real provider requests.

See the [implementation report](../../docs/exec-plans/active/odoo_omnichannel_design_v2/17-inbox-implementation-status.md) for exact verification commands and remaining work.

## Dispatch behavior

An administrator records and confirms recipient authorization evidence for the exact channel, namespace and recipient, with an expiry. Every claim rechecks this evidence and the original approval, requester access, frozen content and selected sender. A confirmed grant must be revoked before it can be replaced; evidence is retained.

The worker commits its attempt before invoking a provider. A timeout or lost result becomes Outcome unknown and blocks the channel. Verify the actual provider outcome, then use Reconcile outcome with explicit evidence. Reconciliation never resends. A verified not-sent outcome closes the command as Failed; replacement requires a fresh prepared message and approval. Pausing or revoking authorization stops unclaimed work, but cannot recall an already committed dispatch.

Only a definite no-send result can retry, with at most five attempts and within approval expiry. Delays use jitter and provider Retry-After; five qualifying failures within five minutes open a five-minute circuit. There is no automatic sender failover.

## Supervised inbox

The Inbox groups verified private text by endpoint and conversation. Operators can assign a conversation to themselves, mark it waiting, close/reopen it, inspect revisions, explicitly link an existing accessible contact and prepare a reply. Preparing a reply does not send it: the original connection must have a healthy selected sender, and consent and separate approval still apply.

Inbound Policies show the exact ingestion and retention scope before activation. Default retention is seven days for pending payloads, 90 days for message/revision content and 30 days for blocked evidence. Legal holds protect previously accepted content from disposal. Incoming messages from already blocked identities never retain a body, even under a hold. Activation does not create contacts or business records or authorize AI disclosure.

Use Blocked Identities to review the exact identity, team/company scope, reason and expiry before confirming. A blank team means Company-wide and requires a system administrator. Unblocking does not replay old messages or grant consent. Intake Events is an administrator-only recovery view; retry is available only for recoverable retained content under the original policy.

Deployment must bind the database by host, enforce HTTPS and proxy limits, and configure a certified adapter and explicitly approved cron operation. Telegram sandbox integration is available in the separate optional addon; it remains disabled until explicit deployment and account authorization. Refresh is manual; groups, attachments and delivery receipts are not yet supported.

## Restore isolation

The native Odoo `data/neutralize.sql` hook disables dispatch, enabled inbound endpoints and Omni schedulers, and pauses active intake policies. It preserves command/approval/attempt history for reconciliation. Invoke Odoo restore/duplicate with `neutralize_database=True` before exposing the copy; default or raw PostgreSQL restores do not invoke this protection. Keep ingress, workers and provider networking isolated until neutralization and reconciliation are complete. Adapter-specific authorization is neutralized by each installed adapter; the Telegram addon supplies its own hook.

## Backend-derived webhook address

No server, domain or URL-preview settings are entered in Omni-Channel.
The endpoint's private `_get_webhook_url()` helper reads Odoo's backend
`web.base.url` through the native `get_base_url()` API. For
`https://example.com`, it returns
`https://channels.example.com/omni/inbound/<route_key>`.
An existing `channels.` prefix is retained, and ports and paths are discarded.
The configured hostname is preserved, including any tenant subdomain:
`erp.example.com` becomes `channels.erp.example.com`. No parent domain is guessed.
The existing Odoo deployment determines the server; no duplicate server address
is stored. Localhost, IP addresses, malformed URLs and local-only domains yield
no public webhook URL. There is no fallback to the incoming request Host header.

This helper provides the URL for a separately approved provider registration;
it does not register a webhook, provision DNS/TLS, move existing registrations,
or activate messaging. DNS and HTTPS for the derived hostname must be available
on the deployment. Upgrade `omni_channel` to `20.0.1.3.2`; this also removes the
superseded manual settings view from installations that loaded the draft.

Operations alerts may reuse Odoo's existing outgoing mail transport. Its SMTP
account is a sending identity, not an automatically selected alert recipient.

## Shared ingress convention

All current and future provider adapters must reuse the core endpoint
`_get_webhook_url()` helper: HTTPS at `channels.[backend hostname]` plus the
endpoint route. Do not add provider-specific server/domain settings or URL
previews. This is a shared addressing convention, not evidence that a catalog
provider is implemented or permission to register its webhook. Existing backend
subdomains are preserved; provider authentication and activation remain separate.

## Operations email alerts (20.0.1.4.0)

Open a channel's **Operations alerts** tab as a system administrator who also
has Omni configuration access to its company and purpose. Choose internal team
members with valid email addresses, then confirm **Enable email alerts**. This
is an explicit automation policy: it enables the shared one-minute scheduler and
permits emails on counter changes and recovery. Installation alone enables
neither the policy nor its cron. No alert recipient or SMTP credentials are
seeded. Mail uses the administrator as author and native `mail.mail` routing,
including existing outgoing-server selection and FROM handling.

The policy monitors only that channel's unknown sends, expired leases, aged
queues/inbox, dead letters, unresolved events, breaker flag and unhealthy selected
senders. Emails contain aggregate counts, not message bodies or customer IDs.
The initial healthy baseline and unchanged counters produce no mail. A changed
nonzero state queues an alert; return to zero queues recovery. Counter changes
within the same severity also notify. This is count-based monitoring, not an
incident-ID tracker; replacement incidents with identical counts do not notify.

Recipients must retain company membership, purpose-team membership, internal
operator access and the approved email addresses. The authorizing administrator
must retain access too. Invalid policies automatically pause before queueing.
Pause before editing recipients; re-enabling records fresh authorization.
Channel row locking and atomic mail/fingerprint writes prevent concurrent
collectors from queueing the same observed change. Batches process up to 100
channels, oldest collection first; real cron execution commits progress per
channel and respects the native cron time budget. For larger deployments,
collection can lag the one-minute interval.

**Pause email alerts** stops new queue entries. Already queued emails retain
approval for delivery by Odoo; inspect/cancel them separately if needed. The last
mail and its native delivery state are visible in the tab; failed mail is kept,
not recreated on every collection. Native mail administration owns retry and
cancellation. Audit records track enable, pause, revocation and queue actions.
Neutralized restores disable policies and the cron.

This does not monitor Odoo's own availability or prove mail delivery. Configure
external process/queue monitoring and test actual delivery/acknowledgement under
separate deployment approval before claiming production readiness. The existing
restricted Telegram shell collector remains a read-only all-company diagnostic;
its output must not be forwarded as a company-scoped email.

Alert verification includes a loopback-only SMTP sink: native Odoo server
selection and MIME delivery are exercised for alert/recovery success and explicit
SMTP rejection. Test fixtures never forward mail; no real mailbox or credentials
are used. Run with `--test-tags=omni_operations` on a disposable database. This
verifies queue-to-SMTP behavior, not real inbox receipt or operator acknowledgement.


## Adapter lifecycle and decommissioning

Catalog and channel readiness use the owning addon's installation state in the
current database, as well as the loaded Python factory. Removing an adapter
immediately makes it unavailable in that database without globally unregistering
it for other databases. Adapter authors must register the owning module with
`register_adapter(code, factory, module="addon_name")`. The no-argument
`installed_adapters()` remains a process-level diagnostic; database/UI callers
must pass `env`. Readiness is not a grant to send or certification of provider health.

Uninstall is not pause. For operational retirement, first pause alerts/dispatch
and intake under their approved controls; review already queued Odoo email,
in-flight/unknown sends, retention/legal holds, and externally registered webhooks.
Uninstall does not unregister a provider webhook or recall a message. Archive or
pause when history must remain available in Odoo.

An inactive, synthetic Telegram adapter uninstall rehearsal preserved core
commands, account records and audit events plus unrelated Approval Center
requests. Telegram-specific fields are removed with the adapter; back up evidence
before teardown. No active external webhook teardown was exercised.

**Uninstalling Omni-Channel core deletes its tables, including command and audit
history.** Native record-level restrictions are not an uninstall retention guard.
Use a separately reviewed destructive decommissioning procedure with retained
backup/export and retention approval. Generic Approval Center requests survived
our rehearsal and new generic drafts remained creatable, but this is not evidence
that Omni-linked approval history remains complete after core removal.
