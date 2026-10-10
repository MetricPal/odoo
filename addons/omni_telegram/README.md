# Omni-Channel Telegram sandbox

Optional Odoo 20 Community addon for supervised private-text intake and approved replies. Version 20.0.1.0.1. Requires `omni_channel` 20.0.1.4.1 from this checkout.

Code and synthetic-provider tests are implemented. **Live sandbox certification and production release remain pending.** Installing this addon does not register a webhook, enable any cron, authorize an account or send a message.

## Supported contract

One bot ID is the account key, namespace, sender key and endpoint key. Private-user IDs are positive canonical numeric IDs; one to ten explicitly authorized test recipients are supported per connection. A reply must originate from a verified conversation on that same bot, have current recipient consent and receive separate Approval Center approval. Plain text only, at most 4096 characters. Link previews are disabled; text is not formatted as HTML or Markdown.

Private text and text edits become the core inbox DTOs. Unsupported groups, topics, business/guest messages, media and callback queries create no conversations or replies. Update IDs deduplicate within the bot account; message IDs are scoped to their conversation. Edit timestamps order revisions; conflicting edits with the same timestamp are quarantined rather than silently overwritten. Inbound shared-secret authentication does not provide a body signature or timestamp freshness guarantee; core durable deduplication, collision quarantine, retention and block checks still apply.

`accepted` records the returned bot/chat/message key. It does not assert delivery or reading. Timeouts, malformed success, redirects and server failures are unknown outcomes and must not automatically resend. Valid API rejections are definite no-send outcomes; only a bounded 429 `retry_after` can request the worker's existing capped retry policy. Manual reconciliation never resends.

## Legacy deployment-controlled secrets

A deployment owner provisions a process environment variable named by the connection's `OMNI_SECRET_...` reference. The value is a JSON bundle with this shape (placeholders, not working credentials):

```json
{
  "database": "EXACT_SANDBOX_DATABASE_NAME",
  "company_id": 123,
  "bot_id": "NUMERIC_BOT_ID",
  "token": "BOT_TOKEN_FROM_APPROVED_SECRET_PROVISIONING",
  "webhook_secret": "RANDOM_32_TO_256_CHARACTERS_USING_A_Z_a_z_0_9_UNDERSCORE_OR_HYPHEN"
}
```

The resolver requires an exact database, company and bot binding, checks the token's bot prefix, and accepts only the fixed environment-reference grammar. Values never enter ORM records, command payloads or ordinary logs. Use an approved secret injection facility on every worker; do not place credentials in source, chat, screenshots, shell arguments or configuration evidence. The private adapter metadata in dispatch claims contains scope and authorized recipient IDs, never credentials. Different databases/companies must have separate scoped bundles; renaming a database requires reprovisioning. A copied database does not inherit permission to use the original bundle.

Outbound HTTPS additionally requires the deployment switch `OMNI_TELEGRAM_SANDBOX_NETWORK=1`. It is off by default. The transport uses only `api.telegram.org:443`, verified TLS/SNI, a checked public numeric DNS address, no proxy environment, redirects or client retries, bounded DNS concurrency, a 25-second call budget, connect/read ceilings of 5/20 seconds and a 1 MiB response-body limit. A dispatch can make three sequential calls (`getMe`, `getChat`, `sendMessage`), within the core 120-second claim lease. DNS threads are daemonized and capped; total HTTP deadlines interrupt header trickling too. Egress instrumentation must redact token-bearing Telegram URL paths.

## Explicit sandbox activation sequence

These are deployment actions for an authorized sandbox operator, not instructions already executed by this implementation:

1. Obtain approval for the sandbox bot, recipient IDs, processing purpose, infrastructure and test message. Provision the scoped bundle and deployment network switch. Recipients must have initiated a private bot conversation and consented to the test.
2. Install the addon on the approved sandbox database. Grant ordinary company/team access and the configuration role. Configure the bot identity, secret reference, recipient list and authorization evidence.
3. Use **Verify and authorize sandbox**. It verifies bot identity with read-only `getMe` and records the human actor/time. Then use the existing sender selection and **Check & Activate** action. These actions never send.
4. Review and activate the inbound processing policy, including retention/hold settings, and explicitly enable the bot endpoint. Configure HTTPS, host-bound database routing, request/proxy limits and restricted access to route/header logs.
5. Separately approve and perform Telegram webhook registration against the exact `/omni/inbound/<route_key>` URL, with the same `secret_token` and `allowed_updates` limited to `message` and `edited_message`. Review any existing webhook and pending-update consequences first. This addon deliberately has no `setWebhook` executor or polling fallback. Never use a `db` query parameter.
6. Separately authorize the core inbox/retention scheduler operation. Verify one real incoming private text and edit, duplicate handling, and rejection of an incorrect secret and unlisted user. Retain sanitized certification evidence.
7. Record and confirm exact recipient consent. Prepare a reply from the inbox and have its assigned, distinct approver approve it. Explicitly enable Telegram sandbox replies on the channel, enqueue the approved command and authorize the dispatch scheduler operation separately. Verify exactly one accepted reply with its scoped provider key.
8. Exercise pause/revoke and unknown-outcome reconciliation in the sandbox. Record results before any release decision. Do not induce ambiguous real sends without a reviewed test procedure.

Revoking sandbox authorization blocks new intake and claims, disables dispatch and advances the channel generation, holding unclaimed work for fresh approval. It cannot recall an in-flight send. Reauthorization does not automatically enable dispatch or refresh held commands. To rotate account configuration, revoke first, resolve any in-flight/unknown work, deactivate the sender where required, change the deployment bundle/configuration, then reverify and explicitly reenable. Changes to credentials at the deployment layer remain privileged operations; the app cannot prevent a deployment administrator from changing its environment.

Adapter registration is process-local trusted code. Another database on the same process may see the adapter as loaded, but it cannot use this provider without the addon’s database-scoped configuration and secret binding. Prefer separate processes for separately governed deployments. Availability is not certification or authorization.

## Verification

Run only on a disposable database, with no real credentials:

```sh
python odoo-bin server -c odoo.conf -d YOUR_DISPOSABLE_TEST_DB \
  --data-dir=/tmp/omni-test-data -i omni_telegram --test-enable \
  --test-tags=/omni_channel,/omni_telegram --stop-after-init \
  --http-port=8077 --max-cron-threads=0
```

Use `-u omni_channel,omni_telegram` for an existing test installation. Chrome and `websocket-client` are required for browser checks. Tests cover provider contract/error mapping, secret isolation, HTTP resource guards, actual webhook routing, governance and browser confirmation. All provider calls are mocked; fixture data is synthetic and does not establish live compatibility.

See the [implementation report](../../docs/exec-plans/active/odoo_omnichannel_design_v2/18-telegram-sandbox-implementation-status.md). Groups, attachments, bulk, delivery receipts, business bridges, AI processing, automatic registration and production certification remain outside this slice.

## Restored and copied databases

Use Odoo's restore/duplicate option with `neutralize_database=True` before starting workers or exposing ingress. Odoo loads each installed module's `data/neutralize.sql`: Omni disables dispatch and enabled endpoints, pauses active intake policies and disables its schedulers; Telegram revokes sandbox authorization. History, approvals, attempts and uncertain outcomes remain intact for reconciliation. Repeating these hooks is safe.

A raw PostgreSQL restore and Odoo's default `neutralize_database=False` do **not** provide this isolation. Restore into a network-isolated environment with cron workers and ingress stopped; explicitly neutralize before bringing it online. Do not inject provider secrets into the restored process. Compare accepted provider IDs and pending/uncertain commands against the source and provider evidence before any separately approved reactivation. A backup cannot undo a message already accepted externally. Neutralization alone is not a measured backup/restore rehearsal or authorization to resume sending.


## Adapter removal

Follow the core [decommissioning runbook](../omni_channel/README.md#adapter-lifecycle-and-decommissioning).
Pause/revoke first and separately review external webhook registration, pending
emails and uncertain sends. Adapter uninstall preserves core command/audit records
but removes Telegram-specific fields. Core uninstall deletes Omni history.
The adapter's readiness now follows this database's installation state even when
another database in the same process still has Telegram installed.
### Creating a Telegram connection at runtime

An Omni administrator selects an allowed company and communication team, chooses
Telegram, and enters the **Bot token** in the masked field. Saving calls Telegram
`getMe`, validates the returned bot ID against the token, and fills the numeric
bot ID, namespace, name, username and verification time. Database scope comes
from the active Odoo cursor, not a user-supplied database name. No manual
`OMNI_SECRET_` provisioning is required for new connections.

Leave **Webhook secret** blank to generate a random secret for a new connection.
An optional replacement must be 32–256 letters, digits, underscores or hyphens.
On an existing connection, blank inputs retain existing credentials. Use the
manager-only **Webhook secret** action to copy the secret for registration;
the bot token is never returned by a record read. **Verify bot** rechecks identity.
Saving/verifying does not authorize the sandbox, register a webhook, select a
sender, enable receiving, or send messages.

Runtime bundles are encrypted using Fernet and stored outside the ORM in private
files under `data_dir/omni_telegram_credentials/<database-sha256>/`. A generated
key and credential files use mode 600; directories use mode 700. The Odoo record
contains only a generated opaque reference and public bot metadata. The key is
local to this Odoo deployment: it does not protect against a compromised Odoo
process or an administrator with access to both key and files. All Odoo workers
must share this directory, with restricted backups of both key and bundles.
Database-only backups cannot restore runtime credentials. Restoring under a
new database name requires fresh credential setup.

Rotation is refused while sandbox authorization or a selected runtime sender
is active. Revoke/deactivate first. Replacement tokens must belong to the same
bot; another bot needs another connection. Existing reference bundles remain
immutable so in-flight claims cannot accidentally resolve a different secret.
Full transaction rollback removes newly written bundles; failed record saves
also remove their new bundle. Successful older versions, and files orphaned by
process crashes or enclosing savepoint rollback, require administrator cleanup
after confirming that no record or in-flight claim still references them.

Legacy environment references remain supported. The dedicated runtime identity
check can call **only getMe** without the sandbox network flag; ordinary adapter
calls and all sending still require the existing deployment switch and approval
checks. No credentials are placed in audit events or returned provider errors.

Tests: `PYTHONPATH=. .venv/bin/python addons/omni_telegram/tests/test_connection_view.py`
and `.venv/bin/python addons/omni_telegram/tools/test_runtime_credentials.py` are
database-free. `test_sandbox.py` additionally covers runtime setup, role/company/
team restrictions, write-only inputs, disclosure and rotation in Odoo.


## Guided channel setup

The six-step channel wizard accepts a masked bot token directly in Credentials,
with the company and communication team already selected in Prepare. Saving
verifies `getMe`, derives the bot ID, creates an encrypted runtime credential
reference and clears the token/secret inputs. An existing verified connection
can be selected instead. Next creates draft bindings idempotently and refuses a
bot already owned by another channel; empty same-team channels remain allowed.

Connect & verify exposes the backend callback URL, manager-only secret disclosure,
consenting sandbox user IDs/evidence, retention policy, connection check and
explicit receiving authorization. Webhook registration is still an administrator
operation; the adapter does not implement `setWebhook`. Missing public HTTPS
configuration is explained in place. A successful bot check does not claim that
a webhook has delivered a message.

Branding edits internal labels. Team & apps shows actual integration availability.
Test & go live selects a received conversation and prepares a draft reply for the
existing permission/approval flow. Explicit sandbox activation uses the existing
sender selection and dispatch actions; it does not bypass approval, networking
or scheduler controls. Saving or finishing never sends a message.


Credential setup errors distinguish invalid input format, rejected tokens,
verification transport failure, rate limiting, provider unavailability, invalid
bot identity, unreadable saved credentials and encrypted-storage failure. Error
messages use fixed categories; they never include provider response bodies,
credential values or raw transport exceptions. Storage errors explicitly indicate
that bot verification succeeded, so users are not told to replace a valid token
for a server filesystem problem.

The setup Verify bot button uses the successful credential-save verification when
new inputs are present, without making a second network request. For a saved
connection it performs an explicit recheck. Last verified records the previous
successful check; a failed recheck does not erase that history. Recheck errors
distinguish unreadable storage from provider verification failures.

Connect & verify shows receiving status, a selectable, read-only callback URL input
and Verify webhook below it. The URL uses the configured public hostname and the
endpoint’s generated route key. Without a public domain, the input shows
`https://channels.<your-domain>/omni/inbound/<route_key>`, substituting the real
route key when available. This display fallback is never treated as a usable
callback URL by verification or receiving. Verify webhook
uses Telegram getWebhookInfo and compares the registered URL exactly, reporting
missing/different registrations and historical delivery errors separately. It does
not register webhooks, verify the secret, enable receiving or prove delivery.
Native collapsed Advanced settings contains secret details, sandbox user
authorization, retention and
credential rechecks. Retention defaults and all authorization gates are preserved.
Enable receiving requires a public callback address; it does not register a
webhook. Open Telegram to test opens the verified bot's public username without
prefilling or sending a message. View received messages uses the existing inbox.
Administrator registration instructions are collapsed in the guidance panel.
