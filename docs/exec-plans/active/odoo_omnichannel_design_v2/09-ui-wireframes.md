# UX specification

Use Odoo-native list/form/search/kanban views first. Existing images in `design/` are visual inspiration; these state and permission requirements govern implementation. Use intentional module/provider icons and translated labels. No permanent primary navigation sidebar or custom SPA.

## Channel overview

Columns: Company, Purpose, Channel, Selected sender, Sender readiness, Configured senders count, Inbound endpoints count, Queue held/unknown count. Group by company/purpose/channel. Unsupported catalog items say Not installed, not Offline. Inbound-only channels are valid and have Outbound unavailable.

## Channel form

```text
Marketing / Telegram                         Company A
Inbound: enabled by policy v3                Outbound: ready

OUTBOUND CONFIGURATIONS                         [Add sender]
(●) Bot A  @marketing       Healthy     Checked 10:42
( ) Bot B  @campaign        Unauthorized [Check health]

[Check & Activate selected candidate]

INBOUND ENDPOINTS
Bot A -> Marketing     Enabled
Bot B -> Marketing     Enabled

[Held commands: 3] [Unknown outcomes: 0] [Audit]
```

Use a radio selector for candidate selection, followed by explicit confirmation. Selection alone does not mutate the runtime sender. Confirm sender, company, purpose, affected queued commands and reason. Failed checks retain previous selection. In-flight/unknown commands prevent selection changes and show resolution actions. No automatic failover toggle.

Provider administrator sees secret reference/readiness, never secret material. Health errors are sanitized. A health check cannot activate sending or register a webhook by itself. Webhook registration is a separate confirmed action showing external side effect.

## Conversation and composer

Header: purpose, company, provider, inbound endpoint, original conversation identity, current selected sender. Timeline has private message content and per-message status. Right-side record links appear only when accessible. Hide unauthorized record names and counts.

Composer actions: Save draft, Submit for approval. Approved command shows Queued, Sending, Accepted, Delivered only when supported, Held, Failed or Outcome unknown. Do not use an ambiguous Send button to hide an approval step.

For mismatched sender: “Reply unavailable: this conversation belongs to Bot B; Bot A is selected.” Provide View channel configuration only to authorized users. Explicit Start new conversation, if supported, creates a new draft with a clear sender/recipient preview; it never impersonates continuity.

## Approval review

Business-named Approval Type and subject; exact sender/account, company/purpose, recipients, full rendered content, attachments, schedule, expiry, action, reason, policy and expected side effect. Approve/Refuse and Request changes; changes create a new revision. Show Enqueued separately from external delivery. Never ask users to type backend model names or methods.

## Blocked identities

Columns: identity display, channel, purpose or Company-wide, reason, source, expiry, actor/time. Confirm block/unblock with scope and reason. Company-wide is visibly broader and requires company-wide governance authority. AI recommendation card has Dismiss and Review block; recommendation does not change enforcement. Blocked payload content is not available in the UI.

## Operations

Queues filter by held reason, unknown outcome, retry age, account and purpose. Reconcile unknown opens evidence entry and provider status where supported. No unconditional Retry button for unknown outcomes. Replacement send previews duplicate risk and creates a new approval.

Quarantine shows sanitized reason, age and authorized reassignment/replay controls. Endpoint reassignment is absent/disabled until P4 workflow exists. Retention shows policy and purge counts; raw payload access is restricted separately from ordinary conversation access.

## Dashboard and reporting

Count provider acceptance separately from delivery and reads. Define response rate as eligible inbound conversations with an authorized human/outbound response divided by eligible inbound conversations in the same documented cohort; exclude blocked/unresolved events. Show timezone and period. Response time uses first eligible inbound to first accepted reply, with median/p95 and excluded cases. No invented SLA labels or fake demo production metrics.

## Accessibility and mobile

Keyboard-operable radio selection, visible focus, meaningful labels, status text alongside colors/icons, screen-reader errors, touch-size actions, responsive forms and readable approval content. Test permission-filtered menus and small-screen approval/reconciliation flow. UI availability mirrors server checks but is never authorization enforcement.
