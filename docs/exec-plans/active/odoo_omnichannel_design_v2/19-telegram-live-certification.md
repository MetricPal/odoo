# Telegram live sandbox certification

Prepared 2026-10-06 against commit `d91a299ca78a` — `feat(omni_telegram): add supervised private-text sandbox adapter`.

Status: live inbound connection verified, real messages and edits received; first outbound reply pending explicit setup/send approval. This record does not certify Telegram connectivity, authorize an unspecified recipient, or mark production gates complete.

## Verified local baseline

Read-only Odoo shell inspection at 2026-10-06 12:55:08 UTC, database `omni_build_20261006`, data directory `/tmp/omni-build-data`:

| Check | Observed result |
|---|---|
| Core installation | `omni_channel` 20.0.1.3.0 installed |
| Adapter installation | `omni_telegram` 20.0.1.0.0 installed |
| Telegram accounts / authorized accounts | 0 / 0 |
| Enabled inbound endpoints | 0 |
| Channels with dispatch enabled | 0 |
| Dispatching or unknown commands | 0 |
| Dispatch / inbox / retention schedulers | All inactive |
| Deployment network switch in inspected shell | Disabled |

The shell read aggregate state only and rolled back. It did not resolve credentials, call a provider, create accounts or alter schedulers. Its environment is not proof of another deployment worker's environment. Inspection log: `/tmp/omni-certification-preflight.log`. The disposable test database is not assumed to be the user's approved live sandbox.

The committed implementation's evidence remains [96 passing regression tests plus 11 Approval Center static checks](18-telegram-sandbox-implementation-status.md). Those are synthetic/mock-provider results and are not repeated as live evidence here.

## Required target information

Record these before executing live steps. Keep tokens, webhook secrets and full secret bundles outside this document and chat.

| Input | Value / state |
|---|---|
| Approved sandbox database and deployment host | Local `omni_build_20261006`, reuse authorized by user |
| Public HTTPS origin, host-bound database routing | Temporary gateway verified; exact database filter; see setup record below |
| Company and communication purpose/team | Awaiting user/deployment owner |
| Approved bot numeric ID | Supplied in conversation; live verification pending |
| Consenting private test recipient numeric ID | ID supplied in conversation; consent/private-conversation eligibility verification pending |
| Provisioned `OMNI_SECRET_...` reference name | Awaiting user/deployment owner; secret value stays in deployment facility |
| Requester, distinct assigned approver and operator | Awaiting user/deployment owner |
| Existing webhook ownership and pending-update handling | Not inspected; must be reviewed before replacing configuration |
| Intake/retention and scheduler operating scope | Not activated |

Proposed outbound test text, to be reviewed in Approval Center for the exact recipient: **“Omni-Channel sandbox verification: this is the single approved test reply.”** Each additional outbound test requires its own approved command. Inbound test text may use **“Omni sandbox intake verification”**, followed by an edit to **“Omni sandbox intake verification — edited”**. Use test-only content.

## Execution and evidence sheet

Follow the [operator runbook](../../../../addons/omni_telegram/README.md) using the actual target. Capture sanitized IDs, times, outcome and relevant audit references. Do not copy tokens, webhook headers, full route secrets or customer payloads into evidence.

| Step | Expected evidence | Result |
|---|---|---|
| Verify target and secret provisioning | Exact database/company/bot binding; approved deployment network switch; access scoped to the chosen team | Pending |
| Verify and authorize bot; select sender | Matching getMe identity, actor/time/evidence, selected sender and generation; no sends | Pending |
| Activate reviewed inbound policy and endpoint | Retention/hold scope, policy and endpoint audit references | Pending |
| Review and register webhook | Owner-approved exact endpoint, matching secret, message/edit update scope; prior registration and pending updates accounted for | Pending |
| Receive test text and edit | One private conversation on the original bot, correct sender/thread/message scope, revision preserved | Pending |
| Replay the same test update | No additional message/effect; event deduplication evidence | Pending |
| Incorrect secret and unlisted test identity | Invalid secret rejected; unlisted identity creates no conversation or reply | Pending |
| Consent, prepare and separately approve reply | Consent evidence and expiry, frozen command, distinct approver, original bot/recipient binding | Pending |
| Explicit dispatch activation and approved execution | One attempt and matching scoped provider message key; recipient observes one reply | Pending |
| Pause/revoke | No new intake/claims; held unclaimed work; any existing in-flight result accounted for | Pending |
| Close certification session | Account/endpoint/dispatch/scheduler end state recorded; no unresolved command silently retried | Pending |

Real transport timeout/failure injection requires a separately reviewed procedure; do not deliberately create a duplicate-risk live send merely to reproduce an already covered local test. A returned Message establishes provider acceptance; recipient observation is separate evidence and does not introduce a delivered/read state into the app.

## Completion boundary

Live sandbox certification can be marked complete only after the actual evidence above is recorded and reviewed. Production release additionally requires the operational, capacity, restore, alerting and UX gates in [acceptance and release](12-acceptance-and-release.md). This checklist does not waive any of them.

Next action: review and approve the concrete [first sandbox reply proposal](20-first-sandbox-reply-review.md). Live inbound setup is complete; outbound permission/configuration changes have not executed. No additional provider implementation is needed to unblock this certification.

## Temporary HTTPS setup — 2026-10-06

User authorized reuse of the disposable database and a temporary tunnel. Odoo is running on loopback port 8077 with an exact database filter, database listing disabled and cron threads stopped. A tested webhook-only gateway is on loopback port 8088. Cloudflared 2026.10.0 was downloaded from Cloudflare's official GitHub release into `/tmp/omni-sandbox-runtime`; no system package/service was installed.

Temporary HTTPS origin: `https://essentially-bin-spelling-saved.trycloudflare.com`. This is a session address, not a stable deployment domain. Process logs live under `/tmp/omni-sandbox-runtime/`. Cloudflare documentation: [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

Verified over public HTTPS: health 204, login 404, database manager 404, webhook without secret 403. Seven standalone gateway/provisioning tests and Ruff checks passed. The gateway does not publish the Odoo UI, database manager or generic RPC routes. No bot token was used, no webhook was registered, no account was authorized and no message was sent. The earlier disclosed token must be replaced before connection.

A [hidden-input provisioning helper](../../../../addons/omni_telegram/tools/README.md) is ready for the rotated token. It creates a private bundle outside the repository; provisioning is still pending. The running Odoo process does not yet have that bundle injected. Bot/recipient identifiers supplied in the conversation are known, but live identity/eligibility checks remain pending.

## Provisioned connection checks — 2026-10-06

The user confirmed private token provisioning. The bundle's ownership, mode 600, regular-file type and database/company/bot binding were validated without printing the credential. Live getMe verified `metric_io_bot`; initial getWebhookInfo found no configured webhook, zero pending updates and no provider error. The private recipient getChat check did not yet verify access; the user was asked to start the bot and send test text.

The requested sandbox configuration now exists under a dedicated Telegram Sandbox purpose and the sandbox administrator. The account recipient list contains only the supplied test ID. Setup records explicitly attribute execution to Codex under the user's request rather than claiming a manual UI action. A one-day pending/message/blocked-content retention policy is configured, with no legal hold. Its policy is active and the endpoint enabled. The sender's first health check was unsuccessful; a subsequent read-only identity check passed and selected the sender. Dispatch remains disabled, no outbound consent was granted and no message command was approved or sent.

The isolated Odoo process was restarted with the bundle injected privately into `OMNI_SECRET_METRIC_TELEGRAM_SANDBOX`. The network switch is enabled for this sandbox process; all cron threads/schedulers remain off. Configured retention is not automatically executed while its scheduler is off: the certification operator must invoke the approved retention cleanup or separately activate its scheduler. Real test content must not be treated as automatically purged merely because a retention period is configured.

Local-only authentication probe: the real webhook header with synthetic invalid `{}` content returned HTTP 400, proving authentication reached schema validation; no event persisted. No real secret was sent through the tunnel by that probe.

Automatic approval review blocked external registration pending explicit approval of the Cloudflare message path. The user subsequently approved that exact webhook registration and message/edit data path. Review separately rejected a public authentication probe because the random webhook-verification header would transit Cloudflare; specific approval of that header transit has been requested and remains pending at this checkpoint. A safer localhost-only probe was completed instead. No rejected action was rerun or bypassed. Provider registration has not occurred at this checkpoint.

## Explicitly approved registration — 2026-10-06

The user explicitly approved the connection scope, including incoming message content and the separate random webhook-verification header passing through Cloudflare. This resolves the earlier approval-review blockers; the bot API token remains private and is sent only to Telegram's API for authenticated provider operations.

The public HTTPS probe with the approved webhook header and synthetic invalid `{}` returned HTTP 400 at schema validation. Registration then completed using `setWebhook` after checking for a conflicting existing webhook. Telegram confirmed the exact endpoint, `allowed_updates` of `message` and `edited_message`, zero pending updates and no reported delivery error. Pending updates were preserved (`drop_pending_updates=false`), with one provider delivery connection configured. Registration evidence was appended to the account audit through the sandbox administrator, explicitly attributed to the agent executing the user's approval. Outbound dispatch remains disabled; no message was sent.

Registration is complete. This does not yet prove delivery/normalization of a real user message, the edit path, approved outbound reply, or overall live certification. The temporary tunnel must remain running for delivery. Inbox processing is invoked manually during certification while all schedulers remain disabled.

Immediately after registration, the manual inbox pass found **two genuine inbound events**, both processed into **two messages in one private conversation**. The conversation identity matches the supplied test recipient. There are zero outbound commands. This closes initial real inbound delivery and normalization evidence, but does not by itself prove edits, duplicate replay, outbound approval or the remaining certification cases. Message bodies were not printed in tool output or copied into this report.

## Next certification checks — 2026-10-06

Configured-endpoint checks passed: duplicate input produced exactly one normalized effect; an incorrect secret was rejected; an unlisted private identity was ignored without a new identity or retained body. These were synthetic local protocol probes inside a rolled-back transaction. All synthetic event/message effects were removed; only the sanitized certification audit was committed. This does not claim observation of an actual Telegram retry.

A real Telegram edit was processed into the existing conversation. At inspection there were three messages and four revisions, with one processed edit event. The user confirmed performing the edit. No original message bodies were included in the report.

The proposed outbound preparation was blocked by automatic approval review because creation of an automation requester, permission assignment, approval policy configuration and submission were not explicitly covered by “go next”. No part of that rejected command ran. The complete [reviewable proposal](20-first-sandbox-reply-review.md) now specifies these sandbox-only changes, exact message, recipient consent, delegated approval recording, at most one send and immediate pause/revocation. Explicit approval has been requested. No outbound command, approval or consent was created by the rejected action, and dispatch remains disabled.

## First approved outbound attempt — 2026-10-06

The user explicitly approved the complete one-reply proposal. The setup initially rolled back on an unset-password type error, then on an uncached policy permission error. No message was sent by those failed setup transactions. The password field is now omitted and verified NULL for the automation requester. The internal policy-active flag check was fixed without changing policy ACLs; its regression first reproduced the failure, then the combined suite passed 98 tests in separate `omni_regression_20261006` (log `/tmp/omni-policy-regression-after.log`). Core 20.0.1.3.1 was applied to the connected local sandbox.

Command 313 / approval 240 received the delegated, explicit human decision, with a distinct requester and approver and temporary recipient authorization. Its single worker attempt completed **failed / definitely_not_sent / invalid_recipient**, with no provider message key. Dispatch was paused and consent revoked immediately; no recurring scheduler or automatic retry was enabled. This is a failed outbound certification case, not a successful live send.

A later read-only preflight found a valid frozen payload and accessible private recipient (getChat HTTP 200, exact ID match). The original safe result code cannot identify which recipient-validation stage failed; no specific network/provider cause is claimed. A fresh, unapproved replacement draft is available under [review 20](20-first-sandbox-reply-review.md), with per-method status diagnostics proposed for a separately authorized new attempt. The previous failed command remains immutable evidence.


## Approved replacement result — 2026-10-06

The user explicitly replied **approve** to replacement draft **314**. Fresh approval request **241** and temporary consent **143** were recorded through the existing scoped requester and distinct Administrator approver. The original failed command 313 and revoked consent 142 remain unchanged.

The governed worker completed exactly **one attempt**, with command state and attempt outcome **accepted**, and provider message key `8541291475:44087589:4`. Safe method diagnostics recorded two getMe checks, one getChat check and exactly one sendMessage call, all HTTP 200 with `ok=true`. Telegram acceptance is verified; recipient observation/read status has not been verified.

After the attempt, dispatch was paused, consent 143 revoked, and the dispatch scheduler confirmed inactive. No automatic retry occurred. The replacement has its own durable invocation marker. Credentials and arbitrary provider response content were excluded from diagnostics. This completes the approved live outbound acceptance check, not overall production certification.

## Restore safety implementation — 2026-10-06

Added native Odoo neutralization hooks in core and Telegram: disable dispatch/endpoints/schedulers, pause active intake policies and revoke copied sandbox authorization while retaining history for reconciliation. The actual hook loader and SQL were tested twice for idempotency with approved queued work, blocked intake and zero sends. Targeted test and the full 20-test Telegram suite passed on the disposable regression database. See the addon restore runbook and `docs/references/odoo20-verification.md` for commands and limitations. An actual backup/restore rehearsal, capacity measurements and alert routing remain release gates. Neutralization is opt-in at Odoo restore; raw/default restores require explicit operational isolation. No live sandbox controls or provider registration changed in this step.
