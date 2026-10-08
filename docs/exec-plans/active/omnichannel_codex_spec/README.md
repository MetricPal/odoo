# Omni-Channel — Codex Implementation Specification

> **Navigation superseded by the user's 2026-10-08 instruction.** The current
> interface is Settings → Technical → Omni-Channel (before Email), with
> Channels, Messages, Policies and Blocklist only. The standalone app, Overview
> and setup wizard described below are historical. Runtime safety requirements
> still apply. See [the simplification report](11_technical_administration.md).

## PURPOSE

This folder is the authoritative product/UI specification for the Odoo Omni-Channel module.

Codex MUST treat this README and the documents in this folder as the implementation source of truth for the Omni-Channel information architecture and UX.

DO NOT preserve the current Omni-Channel UI merely because it already exists.
The current implementation was produced from an earlier specification and must be corrected to match this specification.

## NON-NEGOTIABLE PRODUCT PRINCIPLES

1. Omni-Channel is infrastructure/control-plane administration, not a normal business workflow application.
2. Business users consume channel capabilities inside their own apps/modules.
3. System Administrators configure channels, provider connections, inbound endpoints, outbound senders, routing, policies, blocklists, monitoring and audit.
4. Odoo-native Email and SMS are NOT duplicated by Omni-Channel.
5. The module must support multiple channel types/providers, not Telegram-only behavior.
6. Multiple outbound senders may be configured, but exactly ONE sender can be active for outbound runtime per Channel + Business Purpose.
7. Multiple inbound endpoints may be active for the same Channel + Business Purpose.
8. An inbound endpoint belongs to ONE business purpose/module. Do not allow one receiving identity to ambiguously feed multiple purposes.
9. Outbound sender activation requires a successful health check. Failed health checks MUST prevent activation and MUST NOT replace the currently active sender.
10. Blocklist evaluation occurs before normal inbound business processing.
11. Technical runtime data must not clutter primary business-facing forms.
12. State-changing automation remains subject to the project's explicit human-approval rule.
13. Domain model, navigation, and primary UX are separate concerns. Do not expose every backend model as a top-level menu.
14. Use Odoo 20 Community architecture and conventions as the implementation target.

## FINAL INFORMATION ARCHITECTURE

Primary Omni-Channel navigation:

- Overview
- Inbox
- Messages
- Channels
- Monitoring
- Configuration

There is NO menu named "Advanced Configuration".

Configuration contains:

- Channels
- Connections
- Senders
- Inbound Endpoints
- Routing
- Policies
- Blocklist

Monitoring contains operational/technical visibility such as:

- Health
- Delivery
- Failed Messages
- Activity / Logs

Do not create separate top-level menus for low-level runtime records.

## ODOO TECHNICAL MENU

Omni-Channel technical administration belongs under Odoo's Technical administration area for system administrators/developers.

The normal Omni-Channel experience must not expose technical implementation details to ordinary business users.

When the module is surfaced through Settings > Technical, use "Omni-Channel" as the technical section name. Do not create an artificial "Advanced Configuration" layer.

## FIRST-ENTRY / EMPTY STATE

If the administrator opens Omni-Channel and no channel has been configured:

Show a clean guided empty state, not a technical dashboard and not a list of database records.

Headline:
"Welcome to Omni-Channel"

Description:
"Connect your communication channels and make them available to your teams."

Primary action:
"+ Add Channel"

Show setup progress:

1. Channel
2. Connection
3. Inbound
4. Outbound
5. Verify
6. Activate

The empty state is onboarding only. Once the first channel is configured, the normal Overview dashboard must be shown.

## ADD CHANNEL WIZARD

The wizard is generic. It MUST NOT be Telegram-specific.

Step 1 — Choose Channel
Support the extensible channel catalog, including:
WhatsApp, Telegram, Slack, Instagram, Facebook, LinkedIn, X, TikTok, Threads, YouTube and future providers.

Step 2 — Connection
Connect/configure the provider account. Sensitive credentials/secrets must be protected and never presented as plain text after saving.

Step 3 — Inbound
Configure receiving identity/endpoint and assign ONE business purpose/team/module.

Step 4 — Outbound
Configure available senders. Multiple senders can exist, but exactly one may be active for outbound runtime for the Channel + Business Purpose.

Step 5 — Verify
Run connection/inbound/outbound health checks.

Step 6 — Activate
Activation is allowed only when required verification passes.

After activation, return to the channel detail or Overview. Do not leave the user inside a setup-only screen.

## NORMAL OVERVIEW

After setup, Overview is operational.

It should show:
- Channel health/status
- Channels needing attention
- Connection/provider warnings
- Recent inbound/outbound activity
- Failed delivery indicators
- Pending operational issues
- Add Channel action

Do not fill Overview with raw IDs, leases, route keys, retry counters, provider payloads or database fields.

## CHANNEL DETAIL

Channel detail is the central configuration object.

Show a clear summary:
- Channel name
- Channel type
- Business purpose/team
- Company
- Active/Inactive
- Readiness/health
- Active outbound sender
- Inbound endpoint count

Use tabs/sections for:
- Outbound Senders
- Inbound Endpoints
- Operations
- Alerts

Keep operational controls separate from basic channel identity.

## OUTBOUND SENDER UX

The sender list must clearly distinguish:
- Configured senders
- Active sender
- Health
- Last health check

Use a radio/single-selection interaction for the active sender.

Rules:
- Many configured senders are allowed.
- Exactly one active outbound sender per Channel + Business Purpose.
- Health check MUST pass before activation.
- If the selected sender fails health check, do not activate it.
- The currently active sender remains unchanged on failure.
- Never allow an ambiguous state with multiple active runtime senders.

Technical fields such as provider external key, runtime lease information, raw provider response, etc. belong in technical details/logs.

## INBOUND ENDPOINT UX

Inbound endpoints can be multiple.

Each endpoint must clearly show:
- Name
- Channel
- Business purpose/team/module
- Receiving identity
- State
- Health
- Active/inactive

Technical identifiers such as ownership version, route key, provider event key, etc. must be secondary/technical details.

Inbound processing order MUST conceptually be:

Provider event
→ endpoint validation
→ blocklist check
→ routing/purpose resolution
→ business processing

## BLOCKLIST

Blocklist is a configuration capability.

Allow administrators to block an external identity/number/account for:
- Channel + purpose scope
- Optionally global scope where explicitly supported

Blocked inbound identities must be rejected/held before normal business processing.

AI may recommend a block, but state-changing blocking follows the project's explicit human approval rule unless the product later defines a separately approved policy.

## TECHNICAL DATA

The following are NOT primary form fields:

- Provider Message Key
- Attempt Count
- Next Attempt At
- Lease Expires At
- Ownership Version
- Route Key
- Circuit Until
- Raw Provider Response
- Low-level retry/lease state

They may exist in backend models and technical views.

Expose them through:
- Monitoring
- Delivery/Dispatch logs
- Activity/Audit logs
- Technical Details

Do not delete backend capabilities merely because they are hidden from the primary UX.

## MESSAGES / DISPATCH

"Messages" is an operational view of message records, not a replacement for the user's business workflow.

A message detail may show:
- Channel
- Direction
- Sender
- Recipient
- Status
- Created time
- Business purpose
- Related business record

Technical dispatch details belong under an expandable Technical Details section.

Do not present raw dispatch-engine state as the main message composition experience.

## SETUP VS CONFIGURATION

These are different:

- Add Channel = guided creation wizard.
- Configuration = manage already-created channel infrastructure.

Do not put the setup wizard permanently on the Overview page after configuration exists.

## NAVIGATION RULE

Use "Configuration", not "Advanced Configuration".

Do not create "Advanced" unless there is a real second-level configuration area with a distinct product purpose. In this architecture there is no such need.

## VISUAL/UX QUALITY BAR

The UI must feel like a coherent Odoo business system, not an exposed database administration screen.

Priorities:
- Clear hierarchy
- Few primary concepts per page
- Strong empty states
- Explicit statuses
- Clear active/inactive states
- Progressive disclosure for technical information
- Consistent list/form/detail patterns
- No unexplained fields
- No raw implementation terminology in primary UX
- No accidental mixing of setup, runtime operations and database internals

## DO NOT

- Do not make Telegram the architectural model for all channels.
- Do not expose every model as a menu item.
- Do not show technical fields by default.
- Do not keep "Advanced Configuration".
- Do not allow multiple active outbound runtime senders for the same Channel + Business Purpose.
- Do not activate an unhealthy sender.
- Do not make the first dashboard a raw configuration list.
- Do not duplicate Odoo Email/SMS functionality.
- Do not redesign Hermes Agent as part of this work.

## IMPLEMENTATION ORDER

1. Fix navigation/information architecture.
2. Fix first-entry empty state.
3. Implement generic Add Channel wizard.
4. Fix Channel detail and sender/inbound relationships.
5. Enforce outbound single-active + health-check rules.
6. Enforce inbound purpose ownership and blocklist-before-processing.
7. Move technical details into Monitoring/Technical views.
8. Refine Overview operational dashboard.
9. Preserve existing backend capabilities where valid; change their presentation and placement as specified.
10. Test all supported channel types through the same generic architecture.

## DEFINITION OF DONE

The work is complete only when:

- No "Advanced Configuration" menu remains.
- First-time Omni-Channel entry produces a guided setup experience.
- Add Channel is generic and extensible.
- Telegram is not hardcoded as the conceptual model.
- Multiple outbound senders are supported with exactly one active runtime sender.
- Health check gates sender activation.
- Multiple inbound endpoints are supported.
- Each inbound endpoint has one clear business purpose.
- Blocklist is evaluated before business processing.
- Technical fields are hidden from primary UX.
- Overview is operational after setup.
- Technical administration can live under Odoo Technical settings.
- The UI no longer looks like unrelated backend forms dumped into one menu.
