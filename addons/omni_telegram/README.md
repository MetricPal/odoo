# Omni-Channel Telegram sandbox

Optional Odoo 20 Community addon for supervised private-text intake and approved replies. Version 20.0.1.0.0. Requires `omni_channel` 20.0.1.3.0 from this checkout.

Code and synthetic-provider tests are implemented. **Live sandbox certification and production release remain pending.** Installing this addon does not register a webhook, enable any cron, authorize an account or send a message.

## Supported contract

One bot ID is the account key, namespace, sender key and endpoint key. Private-user IDs are positive canonical numeric IDs; one to ten explicitly authorized test recipients are supported per connection. A reply must originate from a verified conversation on that same bot, have current recipient consent and receive separate Approval Center approval. Plain text only, at most 4096 characters. Link previews are disabled; text is not formatted as HTML or Markdown.

Private text and text edits become the core inbox DTOs. Unsupported groups, topics, business/guest messages, media and callback queries create no conversations or replies. Update IDs deduplicate within the bot account; message IDs are scoped to their conversation. Edit timestamps order revisions; conflicting edits with the same timestamp are quarantined rather than silently overwritten. Inbound shared-secret authentication does not provide a body signature or timestamp freshness guarantee; core durable deduplication, collision quarantine, retention and block checks still apply.

`accepted` records the returned bot/chat/message key. It does not assert delivery or reading. Timeouts, malformed success, redirects and server failures are unknown outcomes and must not automatically resend. Valid API rejections are definite no-send outcomes; only a bounded 429 `retry_after` can request the worker's existing capped retry policy. Manual reconciliation never resends.

## Deployment-controlled secrets

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
