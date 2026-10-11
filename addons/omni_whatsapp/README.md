# Omni-Channel WhatsApp

Separate Odoo 20 Community addon, depending on `omni_channel` only.

Version 1 scope: connect an existing Cloud API account, receive private text in
the inbox, and run one confirmed setup test. This is an inbound/test release;
normal business replies, templates and media are outside this version.
See [offline verification](VERIFICATION.md) for checks, fixes and remaining gaps.

## Implemented

- Odoo module manifest and package.
- Pure GET verification-challenge helper.
- Constant-time HMAC-SHA256 verification against the original POST bytes.
- Bounded text-message parsing scoped to a WABA and phone-number ID.
- Protocol tests with synthetic data and no network or database access.
- Native Connect & verify screen: editable public URL, generated verify token,
  masked app secret and one action for the current state. App secrets are encrypted,
  never model fields or returned UI values. Retention fields remain visible.
- WhatsApp-only GET handler on `/omni/inbound/<route_key>`. It rejects extra or
  duplicated query parameters, wrong tokens, inactive bindings and another host.
  Verification records callback/token possession, not proof of delivery from Meta.
- Module-owned inbound-only adapter. Signed private text uses existing endpoint,
  policy, event deduplication, retention and inbox processing. Non-text/status/group
  notifications are ignored without retaining message content. No receipt reconciliation.
- Explicit Enable receiving authorizes the displayed retention policy. Setup cannot
  skip this step. URL or secret changes disable intake and reset dependent progress.
- Native Credentials screen matching the reviewed layout: Access token,
  Business account ID, Verify account, then discovered Phone number selection.
  Verification does not save; Next rechecks and saves the selected connection.
- Encrypted credential files bound to database, company, team, account and phone.
  Tokens never enter model fields, returned profiles or audit details. Back up
  `data_dir/omni_whatsapp_credentials` (including its private key) separately.
  Database rollback removes newly provisioned credentials.
- Read-only Graph client: checks account access, lists its phone numbers and
  requires explicit selection when several numbers are available. API version
  is supplied by deployment, not guessed or silently upgraded.
- Fixed Graph host, GET-only requests, bearer token outside the URL, TLS
  verification, no environment proxies, redirects or automatic retries,
  bounded response size and pagination. Provider errors use fixed safe codes.
- Final test screen: Tester phone, fixed short message and Send test message.
  The manager confirms the tester's agreement before sending. A verified private
  incoming message from that tester in the last 24 hours is required.
- The diagnostic records a committed attempt before its single POST. Duplicate
  clicks, timeouts and uncertain responses cannot automatically repeat a send.
  Only an explicit provider rejection permits another confirmed attempt.
- Finish requires the manager to confirm receipt, checks the current connection
  and selects the verified number through the native action. Changing the callback
  or app secret clears completion and disables the selected number. An unresolved
  test must be checked with the tester first; it is never silently forgotten.

## Remaining work

Business replies, templates, media and automated/shared webhook registration are
not implemented. Business dispatch remains off. The setup diagnostic is the only
outbound operation. The Graph client and callback flow were checked with synthetic HTTP only;
no live Meta account, public tunnel or actual message delivery was verified.
The final native form still needs a complete logged-in UI tour. Native Form
creation and final receipt confirmation have been checked, as have the actual
Credentials/receiving components. The development-database checker remains
rollback-only. The disposable clean-install checker uses real committed cursors
and two concurrent sessions: one fake send occurs, its pending claim is visible
before sending, and its uncertain result survives caller rollback and blocks retries.
Pending attempts
after a process failure require administrative reconciliation; no automatic retry
or reset is provided.
Reading a phone number is not evidence of sending permission, registration,
webhook delivery or production readiness. Verification has a 25-second workflow
deadline and at most four background reads. Slow read-only requests can outlive
the caller briefly; they cannot write to Odoo or activate anything.

## Deployment prerequisite

Set `OMNI_WHATSAPP_GRAPH_VERSION` to the supported Graph version configured for
your Meta app before starting Odoo. An absent/invalid version produces a short
administrator-configuration error, not a guessed API version or network call.
No tokens or account IDs belong in this setting. Existing saved connections reuse
their encrypted credentials. Changing identity requires a separate channel.

## Onboarding decision

Restart Odoo after Python changes; upgrading a module does not reload imported
Python in an already running process. Configure the trusted HTTPS proxy so Odoo
sees the actual public scheme/host. Host/dbfilter selects the database; callback
query parameters cannot select it.

Save webhook stores local configuration only. Configure the callback and subscribe
to messages in Meta, then click Enable receiving. Use this route for this phone
number only. A batch for another WABA or phone is rejected as a whole, never
silently acknowledged. Shared Meta app/WABA routing and automatic registration
are not implemented. Do not replace a callback used by other numbers.

Connect an existing Meta Cloud API account first. Provide a
[Create a Meta app](https://developers.facebook.com/apps/) link for new accounts.
Use WhatsApp credentials and phone identity, never Telegram fields or test IDs.

## Verification

```sh
.venv/bin/python -m unittest discover -s addons/omni_whatsapp/tests -v
```

`tools/test_credentials_browser.cjs` mounts the actual Owl 3 component with fake
RPC, compiles the inherited template through Odoo's native inheritance engine,
and exercises selection, stale responses, Next saving, unmount clearing and
non-WhatsApp delegation. Set `OMNI_NODE_MODULES` to a Playwright installation.

`tools/check_credentials.py` runs inside an Odoo shell against an installed addon.
It blocks Meta, SMTP and signup emails and rolls back all synthetic records.
It checks manager/operator/portal/team/company boundaries, encrypted saving,
forged profile fields and context defaults, and original other-provider behavior.
It also checks callback HTTP responses with the public-user environment, wrong
tokens/signatures, forged callback fields, foreign phones, native inbox processing,
duplicate retries, explicit authorization and configuration/progress invalidation.
It blocks outgoing POSTs too, exercises the diagnostic's authorization, tester
scope, blocked identities, commit-before-send order, duplicate suppression, receipt
confirmation and native completion. No real test message is sent.
`tools/test_receiving_browser.cjs` renders the real receiving component with fake
RPC, checks native retention saving, state actions and secret clearing, and checks
desktop/mobile overflow. These component checks are not a full logged-in tour.

`.venv/bin/python addons/omni_whatsapp/tools/check_clean_install.py` creates a
unique disposable database, installs WhatsApp without Telegram, validates a
repeat upgrade and native views, and runs the integration checks with actual
concurrent transactions and a fake send transport. It removes that database and
filestore in `finally`; it never commits fixtures in the user's database.

Protocol reference: [Meta webhook sample](https://github.com/fbsamples/whatsapp-api-examples/tree/main/signature-validation-with-webhooks-payloads)
and [Meta WhatsApp webhook reference](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference).
App-secret distinction: [Meta SDK webhook documentation](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/).
Fixed-text test protocol: [Meta sample text message](https://www.postman.com/meta/whatsapp-business-platform/request/q2k7j58/send-sample-text-message).
The tester-first restriction follows Meta's [customer support window](https://www.postman.com/meta/whatsapp-business-platform/folder/fuaee8l/statuses-object).
The SDK is archived and is protocol evidence only, not a runtime dependency.
