# Review: one Telegram sandbox reply

Status: explicitly approved by the user; setup completed after the policy-access fix. Command 313 is approved under request 240, with distinct requester/approver and temporary recipient consent. See the certification sheet for the actual send result. Scope is only `omni_build_20261006` on this machine, company 1, Telegram Sandbox purpose, channel 170, bot `metric_io_bot` (8541291475).

## Exact external effect

Send **one** private plain-text message to test recipient **44087589**, through the verified conversation on the original bot:

> Omni-Channel sandbox verification: this is the single approved test reply.

No attachments, formatting, previews, other recipients, bulk or automated follow-ups. Approval includes the recipient's permission to receive this specific test reply; it must not be inferred from the user starting the bot or sending messages.

## Proposed local configuration and approval actions

1. Create a dedicated internal **Omni Sandbox Requester (automation)** (`omni.sandbox.requester`) with no login password or email. Assign only the Omni Operator role, company 1 and the Telegram Sandbox purpose. It will have neither Omni Administrator nor Approval Center Approver permission. No invitation or email is sent.
2. Add the Approval Center Approver role to the existing **sandbox Administrator** (user 2). Create a company-1 approval policy for this channel requiring that administrator, distinct from the automation requester. This changes only the disposable sandbox. The person approving this review explicitly authorizes the agent to record their decision through that administrator's public approval action, with the delegation stated in audit evidence; no separate human reviewer is invented.
3. Prepare and submit the exact reply from the verified inbox conversation as the automation requester, freezing its content, recipient, sender and policy. Record recipient authorization for this single test with a short expiry, then approve via the assigned administrator's public action after the human approves this review.
4. Verify current bot health, endpoint, consent, approval and unchanged sender/generation. Enable the channel's sandbox dispatch control temporarily, enqueue only this command, and invoke one committed worker claim. All recurring schedulers remain disabled. Abort if any unrelated queued command or dispatch-enabled channel could be claimed.
5. Invoke `sendMessage` at most once. Record the actual provider result with the worker's fencing token. A timeout, lost result or other ambiguity becomes unknown; never retry this certification send automatically. Even a definite no-send result is not permission for a second invocation in this test.
6. Pause dispatch after the attempt and revoke the temporary recipient authorization. Preserve the command, approval and outcome audit. An unknown/in-flight outcome must remain visible for reconciliation; no false success or cancellation is recorded.

## Review evidence and constraints

- The configured bot identity and webhook are verified; two genuine incoming messages were previously normalized into one private conversation for this recipient.
- Configured-endpoint probes confirmed one effect from a duplicate, rejection of an incorrect secret, and ignored unlisted identity without body/identity creation. These probes were synthetic and their inbox changes were rolled back; only a sanitized audit result remains. They are not actual Telegram redelivery evidence.
- A real edit has been requested separately; record its observed result in the certification sheet. This proposal does not fabricate that evidence.
- Existing core and provider tests cover immutable approvals, distinct approvers, token fencing and unknown outcomes. This is the first actual provider send, not production certification.
- Credentials stay in the private bundle. The bot token is used only with Telegram's API; no credentials go into this document, message or command payload.
- Provider acceptance and the user's observation of the reply are separate evidence. There is no delivery/read-receipt claim.

## Approval needed

Approve the exact sandbox permission/configuration changes, delegated recording of your approval, recipient consent, **one send of the displayed text**, and immediate dispatch pause/consent revocation afterward. Declining leaves outbound sending disabled.

Automatic approval review rejected the initial attempt to create the requester, assign roles, configure a policy and submit the reply because “go next” did not explicitly authorize those exact persistent state and permission changes. None of that rejected command executed. This document makes the complete proposed action concrete before another execution attempt.

## Approved execution and result

The user selected **Approve setup and one test reply**. Setup created the scoped requester without a password, assigned the distinct sandbox Administrator approver, recorded explicit one-message recipient consent, and approved command **313** under request **240** through the existing public actions. A cold-cache policy-access issue was reproduced and fixed first; the separate regression database passed all 98 tests. See `docs/references/odoo20-verification.md` for the narrow fix and access assertions.

One worker attempt was made. The final command state is **failed**, outcome **definitely_not_sent**, reason **invalid_recipient**, with no provider message key. Dispatch was immediately paused, the temporary consent revoked, and the dispatch scheduler remains off. The one-time local invocation marker and retained command prevent guessing/replaying the attempt. No second invocation was made under this approval.

Subsequent read-only diagnosis found the frozen payload valid and Telegram getChat returned HTTP 200 with the exact recipient ID and private-chat type. The recorded failure does not distinguish failed recipient preflight from a send rejection; the original provider response is intentionally not retained. Do not infer a specific transient cause or retroactively mark the failed command accepted.

## Fresh replacement review

Unapproved replacement draft **314** is prepared via the existing copy action, preserving the verified conversation restriction and exact text/recipient above. It carries no approval, consent or attempt from the failed command. A new approval would authorize one new attempt through the existing requester and distinct Administrator policy, a new short-lived consent grant, explicit enqueue/temporary dispatch activation, and immediate pause/revocation afterward. All recurring schedulers remain off. It must not automatically retry.

During that separately approved attempt, record only provider method, HTTP status/error code and whether sendMessage was invoked. Never record the token, webhook secret, URL path, headers, arbitrary provider description or recipient content. This adds diagnostic evidence without mocking or bypassing the real adapter, preflight, approval or committed worker.


## Approved replacement result — 2026-10-06

The user explicitly replied **approve** to replacement draft **314**. Fresh approval request **241** and temporary consent **143** were recorded through the existing scoped requester and distinct Administrator approver. The original failed command 313 and revoked consent 142 remain unchanged.

The governed worker completed exactly **one attempt**, with command state and attempt outcome **accepted**, and provider message key `8541291475:44087589:4`. Safe method diagnostics recorded two getMe checks, one getChat check and exactly one sendMessage call, all HTTP 200 with `ok=true`. Telegram acceptance is verified; recipient observation/read status has not been verified.

After the attempt, dispatch was paused, consent 143 revoked, and the dispatch scheduler confirmed inactive. No automatic retry occurred. The replacement has its own durable invocation marker. Credentials and arbitrary provider response content were excluded from diagnostics. This completes the approved live outbound acceptance check, not overall production certification.
