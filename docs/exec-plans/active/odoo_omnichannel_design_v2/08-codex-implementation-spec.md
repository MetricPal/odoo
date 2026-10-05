# Codex Implementation Specification

## Goal
Build an Odoo Community module named `omni_channel` as the reusable communication/social integration layer for business modules such as Marketing, Sales, Recruitment and HR.

Target: Odoo 20 Community. Do not depend on Enterprise-only models or features.

## Non-goals
- Do not replace Odoo's native Email Marketing.
- Do not replace Odoo's native SMS Marketing.
- Do not create a second generic email/SMS campaign engine.
- Do not allow an AI agent to autonomously execute external state-changing actions; actions must pass the existing human approval policy.

## Core Cardinality Rules
For every `(business_module, channel_type)`:
- exactly 0..1 logical OUTBOUND channel; when configured, it is unique.
- 1..N INBOUND endpoints are allowed.
- an inbound endpoint belongs to exactly one business purpose/module.
- the same external inbound endpoint/address cannot be assigned to two purposes simultaneously.
- outbound is logical; it may resolve to one configured sender identity/provider account.
- inbound is endpoint-oriented: phone number, bot, page, account, workspace/channel, etc.

Example:
Marketing + WhatsApp = 1 outbound + N inbound numbers.
Sales + WhatsApp = 1 outbound + N different inbound numbers.
The same WhatsApp inbound number cannot belong to both Marketing and Sales.

## Recommended Odoo Models
Use clear `_name` values and normal Odoo ORM patterns.

- `omni.channel.type`: provider/channel catalog (whatsapp, telegram, slack, discord, linkedin, facebook, instagram, x, tiktok, youtube, threads, pinterest).
- `omni.provider`: provider/API integration definition.
- `omni.account`: authenticated external account/business account/workspace.
- `omni.channel`: logical module + channel configuration. Fields should include name, channel_type_id, business_model/module key, direction/configuration, active, company_id, provider/account references, capabilities.
- `omni.inbound.endpoint`: inbound address/endpoint; endpoint_type, external_id/address, display_name, channel, purpose/module, account, active, verification state, webhook metadata.
- `omni.outbound.sender`: logical outbound sender binding; channel, provider account, external sender identity, active, default flag.
- `omni.capability`: capability catalog and endpoint/account support flags.
- `omni.conversation`: normalized conversation/thread abstraction.
- `omni.participant`: normalized external participant identity.
- `omni.message`: normalized inbound/outbound message/event record.
- `omni.attachment`: normalized media/document metadata.
- `omni.webhook.event`: raw inbound webhook/event envelope with deduplication key and processing state.
- `omni.delivery`: outbound delivery state, provider message ID, timestamps, error data.
- `omni.template`: provider/channel-specific message template metadata; do not duplicate Odoo email/SMS template engines.
- `omni.routing.rule`: optional routing/assignment rules after endpoint ownership is resolved.
- `omni.approval.request`: only if an existing approval framework is unavailable; otherwise integrate with the existing approval layer.

Do not create a Python model per provider. Use adapter classes/services.

## Provider Adapter Contract
Create a stable interface, for example:
- `authenticate()` / credential validation
- `get_account_info()`
- `verify_webhook()`
- `parse_webhook(payload)` -> normalized events
- `send_message(command)`
- `send_bulk(commands)` where provider permits it
- `create_post(command)` where supported
- `comment(command)` / `reply(command)` where supported
- `like(command)` where supported
- `get_conversation()` where supported
- `health_check()`

Adapters must expose capabilities instead of pretending every provider supports every action.
Provider-specific limitations remain inside the adapter.

## Inbound Pipeline
1. Receive webhook/event.
2. Verify signature/token where supported.
3. Store raw event before processing.
4. Generate deterministic idempotency/deduplication key.
5. Resolve provider/account.
6. Resolve inbound endpoint using external endpoint identity.
7. Enforce endpoint's single business purpose.
8. Normalize participant and message.
9. Create/update conversation.
10. Create message and delivery/event records.
11. Route to the owning Odoo module/business record.
12. Emit internal bus/event for UI refresh.

Unknown endpoints must not silently route to a module. Put them into an unresolved/failed state for configuration.

## Outbound Pipeline
1. Business module requests an action through the service layer.
2. Resolve exactly one logical outbound channel for `(module, channel_type)`.
3. Resolve sender/account.
4. Check capability, permissions, provider limits and approval requirement.
5. Build normalized command.
6. Execute only after approval where the action changes external state.
7. Persist provider request/result.
8. Persist delivery status and provider ID.
9. Retry transient failures with bounded exponential backoff.
10. Never duplicate a successful outbound action when retrying.

## Bulk Messaging
Bulk is a service operation, not a second channel.
- Accept a campaign/job and recipient set.
- Deduplicate recipients.
- Apply provider rate limits.
- Queue jobs.
- Persist per-recipient delivery status.
- Support pause/cancel where safe.
- Report sent/failed/pending/replied metrics.
- Respect provider policies and opt-out/consent fields available in Odoo.

## Social Actions
Normalize these where the provider supports them:
- post/create content
- comment
- reply
- reaction/like
- direct/private message
- delete/archive only where explicitly supported and approved

Do not expose unsupported capabilities in the UI.

## Security
- Company-aware access rules.
- Only authorized users can view/edit provider credentials/configuration.
- Never expose access tokens in normal list/form views, logs, chatter, exports or error messages.
- Encrypt/seal credentials using an appropriate Odoo-safe mechanism; store references/secrets separately where possible.
- Separate configuration permissions from operational messaging permissions.
- Add audit fields and an immutable-ish audit trail for external actions.
- Use record rules to prevent cross-company leakage.

Suggested groups:
- Omni Channel User
- Omni Channel Manager
- Omni Provider Administrator

## UI Specification
Menus:
Omni Channel
- Dashboard
- Channels
- Inbound Endpoints
- Conversations
- Messages
- Social Posts
- Providers / Accounts
- Capabilities
- Webhook Events
- Deliveries
- Configuration

### Channels list view
Columns:
- Name
- Business Module
- Channel
- Outbound configured
- Inbound endpoint count
- Account
- Capabilities summary
- Company
- Status

Filters:
- Module
- Channel
- Active/Inactive
- Has outbound
- Has inbound
- Company

Group by:
- Business Module
- Channel
- Company

### Channels kanban
Card should show:
- channel icon/type
- module/purpose
- `Outbound: Configured/Not configured`
- `Inbound: N endpoints`
- provider/account
- health/status
- capability chips

### Channel form
Sections:
1. General: Name, Module/Purpose, Channel Type, Company, Active.
2. Outbound: sender/account, external identity, capabilities, status.
3. Inbound Endpoints: embedded list with endpoint, external address, status, purpose.
4. Capabilities: supported/disabled capabilities.
5. Webhooks: verification/status and endpoint metadata.
6. Health: last check, last successful event, last error.
7. Audit/metadata.

Critical UX: visually separate OUTBOUND from INBOUND so the 1-vs-N rule is unmistakable.

### Inbound Endpoint list
Columns:
- Endpoint
- Channel
- External Address/ID
- Purpose/Module
- Account
- Verification
- Last inbound event
- Active

### Inbound Endpoint form
- Channel
- Endpoint type
- External address/ID
- Purpose/module (required and readonly after activation unless reassignment workflow is used)
- Provider account
- Verification status
- Webhook status
- Active

Prevent saving an endpoint already owned by another module.

### Conversation list
Columns:
- Subject/name
- Channel
- Purpose/module
- Participant
- Last message
- Direction
- Status
- Assigned user
- Unread count

### Conversation kanban
Cards grouped by status or assigned user. Show channel icon, participant, last message preview, unread count and SLA/age where applicable.

### Conversation form
Three-pane intent:
- header: channel, participant, purpose, assigned user
- message timeline
- composer with capability-aware actions
- right-side metadata/context links to CRM/contact/application/etc.

### Message list
Filters for inbound/outbound, channel, provider, delivery state, date, module.

### Delivery/reporting dashboard
KPIs:
- inbound messages
- outbound messages
- delivered
- failed
- response rate
- conversations opened
- conversations resolved
- posts published
- comments/replies
- bulk job progress
- provider health

Charts:
- volume over time
- inbound vs outbound
- channel distribution
- delivery status
- module distribution
- response time

### Social Post form
- Channel/account
- content
- media
- scheduled/pending/approved/published status
- provider capability warnings
- preview area
- approval status
- external post ID

Do not show social actions unavailable for the selected provider.

## UX State Rules
Use clear states:
- Draft
- Pending Approval
- Approved
- Queued
- Processing
- Sent/Published
- Delivered
- Failed
- Cancelled
- Unresolved
- Disabled

## Constraints and Validation
At database/ORM level where possible:
- one active outbound per module + channel type + company.
- one active inbound endpoint identity per provider/account/address.
- endpoint must have exactly one purpose/module.
- channel type must be active before configuration.
- outbound sender must belong to the selected provider/account.
- capability must be supported before an action can be created.

## Queue / Reliability
Use Odoo's available job/cron infrastructure without introducing a mandatory external runtime dependency for the core module.
- webhook processing must be idempotent.
- outbound jobs need retry counters, next retry time, last error and final failure state.
- provider timeouts must not block HTTP webhook responses.
- raw webhook events should be retained for troubleshooting according to configurable retention.

## Tests
Codex must create automated tests for:
1. one outbound constraint.
2. multiple inbound endpoints.
3. endpoint exclusive ownership across modules.
4. inbound routing.
5. unknown endpoint handling.
6. webhook signature validation abstraction.
7. idempotent webhook processing.
8. outbound capability validation.
9. approval gate for state-changing actions.
10. retry behavior without duplicate sends.
11. company isolation.
12. access groups/record rules.
13. bulk job per-recipient status.
14. UI view/action/menu loading.
15. provider adapter mock tests.

## Acceptance Criteria
The implementation is acceptable only if:
- Marketing can have 1 WhatsApp outbound and N WhatsApp inbound endpoints.
- Marketing can independently have 1 Telegram outbound and N Telegram inbound endpoints.
- Sales can have its own WhatsApp configuration without sharing Marketing's inbound endpoint.
- An inbound endpoint cannot be assigned to Marketing and Sales simultaneously.
- Email and SMS are not reimplemented by this module.
- Unsupported provider capabilities cannot be executed through the generic service.
- Webhooks are idempotent.
- External state-changing actions cannot bypass the configured approval policy.
- The UI makes the 1 outbound / N inbound model obvious.
- Core code does not contain provider-specific business logic outside adapters.
- New providers can be added without changing the core conversation/message models.

## Coding Rules for Codex
- Follow Odoo 20 Community conventions.
- Keep provider integration behind interfaces/adapters.
- Prefer ORM constraints over UI-only validation.
- Keep controllers thin; business logic belongs in services/models.
- Use translatable user-facing strings.
- Add access CSV and record rules.
- Add XML views, actions and menus.
- Add tests with deterministic mocked providers.
- Do not silently fall back from one module's channel to another module's channel.
- Do not invent provider API behavior; mark provider-specific TODOs where credentials/API details are required.
- Keep implementation modular so future channels can be installed/configured independently.

## Outbound Sender Pool: Multiple Configurations, Exactly One Active

Outbound configuration is **0..N**, but runtime activation is **0..1 active sender** for each `Module + Channel Type`.

Example:

```text
Marketing + WhatsApp
  ├── WhatsApp Business #1  configured
  ├── WhatsApp Business #2  ACTIVE  <- runtime sender
  └── WhatsApp Business #3  configured
```

### Invariants

- Admin may configure multiple outbound sender identities.
- At most one sender may have `is_active = true` for the same `module_id + channel_type`.
- Normal outbound workflows MUST resolve the active sender at runtime.
- An inactive configured sender MUST NOT be used by normal workflows.
- Activating a sender MUST perform a real provider health check first.
- Failed health check MUST NOT change the current active sender.
- No automatic failover is permitted.
- If the active sender later becomes unhealthy, mark it unhealthy and block outbound; require explicit administrator activation of another sender.
- The one-active rule must be enforced at database level as well as UI level.

### Suggested Model

`omni.outbound.sender`

```text
module_id
channel_type
provider_account_id
display_name
external_sender_id
external_sender_address
credentials_reference
status
health_status
health_checked_at
health_message
is_active
last_activated_at
last_deactivated_at
```

Health status:

```text
unknown | healthy | degraded | unhealthy | expired | not_found | unauthorized
```

### Database Constraint

Conceptually enforce:

```sql
UNIQUE(module_id, channel_type) WHERE is_active = TRUE
```

The implementation must also protect concurrent activation attempts transactionally.

### Activation Flow

```text
Select sender
  -> Check permissions
  -> Provider health check
  -> If healthy: deactivate old active sender
  -> activate selected sender
  -> commit
```

If the check fails, rollback and retain the previous active sender.

### Provider Adapter Contract

Every provider adapter must expose a normalized operation such as:

```python
check_sender_health(sender) -> HealthCheckResult
```

Core code must not contain provider-specific API logic.

### Runtime Send Flow

```text
Module -> Channel Type -> Active Outbound Sender -> Provider Adapter -> External Provider
```

If there is no healthy active sender, outbound is blocked with a clear business error.

### Audit Events

Record:

- `outbound_sender_activated`
- `outbound_sender_deactivated`
- `outbound_sender_health_check`
- `outbound_sender_health_failed`

Audit fields should include user, module, channel, sender, previous active sender, new active sender, timestamp, health result and reason.

### Acceptance Criteria

1. Multiple outbound senders can be configured for Marketing/WhatsApp and every other supported channel.
2. UI presents them as a radio-button-style single selection.
3. Activation performs a provider health check.
4. Unhealthy senders cannot become active.
5. Failed activation leaves the previous active sender unchanged.
6. Only the active sender is used for runtime outbound sending.
7. Concurrent activation cannot create two active senders.
8. No automatic failover occurs.
9. All activation and health events are auditable.

## 8.6 Inbound Blocklist & AI Moderation

The Omni-channel system MUST support blocking an inbound external identity before normal business processing.

Default scope: `Module + Channel + External Identity`.

A blocked identity MUST NOT create a normal Conversation, Lead, Contact, workflow, notification, or invoke the normal AI conversation agent. The block check occurs immediately after provider verification and identity normalization.

Pipeline:
`Webhook -> Verify -> Normalize Identity -> Blocklist Check -> Endpoint/Module Routing -> Conversation/Workflow/AI`

Create `omni.blocked.identity` with fields such as `module_id`, `channel_type`, `external_identity`, `external_identity_type`, `provider_account_id`, `reason`, `category`, `source`, `blocked_by_user_id`, `blocked_at`, `active`, `expires_at`, `notes`, `last_seen_at`.

Categories: `spam`, `abuse`, `harassment`, `irrelevant`, `fraud`, `malicious`, `unwanted`, `other`.
Sources: `manual`, `rule`, `ai_recommendation`, `provider`, `import`.

Support Global blocking as an explicitly broader scope. Module-scoped blocking must not block the same identity from another module.

Phone/external identities must be normalized before comparison.

Blocked events may be audited with minimal metadata; do not unnecessarily retain blocked message content.

Provider-level blocking is optional and adapter-based. Local Omni blocking must work even when the provider has no block API.

### Inbound Moderation Agent

Add an `Inbound Moderation Agent` capable of classifying inbound messages as `legitimate`, `irrelevant`, `spam`, `abuse`, `harassment`, `fraud`, `malicious`, or `unknown`, with a risk score and confidence. Recommendations may be `allow`, `flag`, `review`, or `recommend_block`.

AI recommendation does NOT execute the block by default. Because blocking changes system state, explicit human approval is required.

Store moderation decisions separately, including model/provider, policy version, classification, risk, confidence, recommendation, approver, approval time, and executed action.

Repeated-offender signals may be used for recommendations, but frequency alone must not automatically block unless an explicit deterministic policy is configured.

Acceptance tests MUST cover blocked inbound rejection before conversation creation, module-scoped blocking, global blocking, unblock behavior, AI recommendation requiring approval, and complete auditability.
