# Omni-Channel

Odoo 20 Community foundation for company- and purpose-scoped communication.

## Available in 20.0.1.9.0

- Native channel kanban/list/forms and a deliberate app icon.
- Twelve channel catalog entries, explicitly marked unavailable without an installed adapter.
- Company/purpose ownership, connection references, outbound sender configurations and inbound endpoint configuration.
- Radio selection of one runtime sender, verified health, stale-selection protection, database uniqueness and explicit deactivation.
- Prepared messages with immutable submission snapshots, distinct assigned approvers, expiry, refusal/cancellation and idempotent local enqueue.
- Scoped integration with the existing Approval Center; ordinary requests retain their existing behavior.
- Append-only application audit, secret-reference field restrictions and server-side RPC/default-context protections.

- Persisted dispatch attempts, fenced leases, current approval/recipient checks, throttling, bounded safe retries and recovery to unknown outcomes.
- Recipient authorization records, pause controls, read-only attempt history and evidence-based manual reconciliation.

## Technical administration

Omni-Channel is infrastructure, not a standalone application. With developer mode
enabled, system administrators open **Settings → Technical → Omni-Channel**,
before **Email**. The section contains only **Channels**,
**Messages**, **Policies**, and **Blocklist**. Messages is a read-only delivery
monitor, with waiting-to-send and needs-attention filters; composition remains
available to the existing business integration actions.

Channels uses the native Odoo kanban/list switcher, search, filters, grouping,
and pagination (80 records per page). The left **Communication teams** search
panel lists existing teams such as Sales and HR, with counts and an All option.
Team selection combines with search and channel-category/archive filters. Group
by team, channel type, or company where permitted. Extra list columns are hidden
by default and available in the native column selector. Kanban cards cannot be
dragged to change team or company. Existing team membership and company access
rules apply to results and counts.

**New** in Channels opens six steps matching the design: **Prepare → Credentials
→ Connect & verify → Branding → Team & apps → Test & go live**. The native search
panel is a transparent stepper, the center uses native form fields, and the right
panel explains the selected step. Completed stages have green check circles;
the current stage is purple with padded, rounded selection. Small screens stack
guidance below the form and steps above it.

Next saves through Odoo and validates the current stage before advancing; later
unvisited stages cannot be skipped. Credentials stay in the wizard. The provider
adapter prepares draft sender/endpoint bindings and a draft receiving policy;
this never activates delivery. Connect & verify requires a healthy, explicitly
enabled endpoint before it is marked complete. A credential check is not proof
of webhook delivery: the final step uses an actual received conversation.

Company and communication team are selected before credentials for scope
validation and become fixed when identities are bound. Branding controls
internal names only. Team & apps identifies the available Inbox and explicitly
labels business-app integrations that are not implemented. Review test reply
creates a draft for separate consent/approval. Finish setup only saves; provider
activation remains a separate confirmed action. Unsupported providers remain
saved drafts with a clear explanation in Credentials.

Messages and Connections are available from the channel header. Operations →
Technical Details links to delivery logs, intake logs, purpose audit history and
recipient authorization. Purpose/team records remain editable through their
relational field. No separate Overview, Inbox menu,
configuration tree or app launcher is installed. Existing inbox actions and
business integration APIs remain available to consuming applications.

The catalog and configuration are generic for all channel types. Provider
adapters are still required for actual sending/receiving; catalog membership is
not a working integration. Sender health, ownership, company/purpose scope,
blocklist-first intake, approvals and audit rules are unchanged.

## Operational boundary

This is a foundation release with a transport-neutral outbound worker. Its cron and each channel ship disabled; core alone exposes no public enable action. The optional `omni_telegram` addon adds explicitly authorized sandbox reply activation. Verified webhook handling and a private-text inbox processor are installed. Core includes no production adapter or credential resolver; the optional [Telegram sandbox addon](../omni_telegram/README.md) provides a scoped resolver and bounded private-text transport, with live certification still pending. Endpoint intake and the inbox/retention cron jobs default to disabled; activation requires a release-ready adapter and explicit processing policy. Queued means retained locally. Accepted means the provider acknowledged the send, not that the recipient received it. Automated tests use mocks only.

The existing production database was not upgraded. Installation and tests used `omni_build_20261006` with data under `/tmp/omni-build-data`.

## Configure access

1. In Settings, a system administrator grants Omni-Channel Administrator to configuration owners and Operator to reviewers/requesters as appropriate.
2. A system administrator assigns internal users to Communication Teams. A role alone does not grant purpose membership; selected Odoo companies also restrict access.
3. Configure named channels for the company, communication team and channel type. A team may have several channels of the same type, including when older channels are archived. Configure connections under that same scope. Generic credential-reference fields accept only references. With the Telegram adapter installed, enter a token in its dedicated masked Bot token field; saving verifies and stores it securely.
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

Independent transaction tests (`omni_operations_transactions`) verify real
PostgreSQL lock contention, safe collection after serialization retry, and atomic
rollback after queue insertion or snapshot flush. They commit and clean uniquely
identified synthetic fixtures, so run only on a disposable database. These tests
prove durable queue deduplication, not exactly-once SMTP delivery.


## Clear administration forms (20.0.1.9.0)

Policy, blocklist and message fields use labels above inputs in a responsive
two-column layout. Each retention period has an explanation beside the input:
conversation text, temporary incoming processing data, and blocked-event history.
The latter is distinct from block expiry; deleting history never unblocks anyone.

Choose a Connection when creating a block. Company, channel type, team and
provider account scope are filled automatically and validated on the server.
Existing integration-created blocks without a connection remain supported.
Provider details and change history are secondary sections.

Channel configuration explicitly warns when no provider adapter is installed.
Catalog entries for WhatsApp, LinkedIn and other services do not imply live
integration support; only the existing Telegram sandbox adapter is supplied.

### Multiple channels for a communication team

Version 20.0.1.10.0 removes the old channel scope uniqueness constraint. Upgrade
`omni_channel` to apply the included idempotent pre-migration on existing databases.
It drops only `omni_channel_scope_unique`; no channel is deleted or unarchived.
Provider-account, outbound-sender and inbound-endpoint identity uniqueness,
per-channel runtime sender selection and company/team access rules still apply.

### Responsive channel setup

The guided setup responds to its content width, including split browser windows.
Above 1200px, the form and guidance sit side by side. At 1200px and below,
guidance stacks under the form. At 767px and below, the steps wrap above the
form and their secondary hints are hidden; labels, step numbers and selected
state remain visible. Footer buttons retain their natural height and wrap.
The left panel stays transparent. Styles apply only to the setup view.


Connection setup starts with the native horizontal choice **Create new connection**
or **Use existing connection**. New shows credential inputs; existing shows only
the saved-account selector and public bot details. Switching choices clears
unsaved secrets. After verification creates a connection, the choice changes to
existing. Once bindings exist the choice is locked. The wizard cannot replace
an existing connection's credentials. The right-hand **About this step** panel
shows only instructions for the selected choice; later steps are unchanged.

Prepare contains only the four setup fields. Its explanation appears once in
About this step; credential and receiving requirements appear in their own steps.


Channels cards and lists show saved setup progress out of six steps. Managers
can use Continue setup to reopen the last completed step (or Prepare when none are complete). The native
Incomplete setup filter selects records with fewer than six recorded steps.
Progress advances only after the current step passes server validation; revisiting
a step does not count it twice, and Finish setup records the sixth step without
activating delivery. Older channels start with no recorded wizard progress;
readiness is not used to invent completed setup steps.

Channel cards and list rows use native Odoo `can_open="false"` for kanban and the list renderer’s
`noOpen` flag through the registered Channels parser. Odoo 20’s list XML schema
rejects `no_open`, so it is not placed in XML. Record navigation is button-only: Start setup / Continue setup for
unfinished channels, Open channel for completed channels. No controller click
interception or CSS pointer blocking is used. Resume opens the last completed
step. The sidebar allows only completed steps and the current step; Next
validates and advances into unfinished steps.


When receiving is unavailable, Connect & verify offers Set up receiving later.
This saves the draft and permits Branding and Team & apps without completing the
receiving step. Per-step progress preserves the gap (four of six after those
steps); old contiguous progress is read compatibly. Test & go live offers Save
draft or Finish receiving setup until receiving passes validation. Direct RPC
cannot finish setup with deferred receiving or forge step completion. Deferring
never authorizes intake, registers a webhook, sends a message or activates dispatch.
