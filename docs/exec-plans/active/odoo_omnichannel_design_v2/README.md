# Omni-Channel implementation plan

Revised: 2026-10-06. Status: configuration, governed preparation, transport-neutral worker and supervised private-text inbox implemented; optional Telegram sandbox adapter implemented; live-provider certification and production release pending. See [Telegram implementation status](18-telegram-sandbox-implementation-status.md), the [live certification evidence sheet](19-telegram-live-certification.md), and the [first reply review](20-first-sandbox-reply-review.md).

## Purpose

Build a reusable Odoo 20 Community communication layer for Marketing, Sales, Recruitment and HR. Business applications own business records; Omni owns transport, communication records and routing. Email and SMS keep their native Odoo sending engines. No Enterprise dependency is assumed.

## Canonical architecture

For each company + business purpose + channel type, configure at most one logical channel. That channel contains 0..N configured outbound senders, at most one active sender, and 0..N inbound endpoints. Every physical inbound endpoint has one owner. An inactive sender can never be used to reply. Incompatible replies remain blocked; the UI explains the sender limitation.

Humans approve external side effects. Approved commands are immutable and queued durably. Sender changes never silently rewrite an approved command. Inbound ingestion runs only under an explicitly activated processing policy, with no implicit permission to create CRM/HR records or send replies.

## Reading order and authority

Project contracts in `docs/` and AGENTS.md govern this package. The following files replace the earlier draft wording; there is no implicit last-section-wins interpretation:

1. [Core rules](02-core-rules.md): normative invariants.
2. [Data model](03-data-model.md): entity ownership, keys and lifecycle.
3. [Odoo integration](04-odoo-integration.md): verified extension points and dependencies.
4. [Implementation specification](08-codex-implementation-spec.md): service and transaction contracts.
5. [Security and operations](11-security-and-operations.md): authorization, privacy, operating defaults.
6. [Acceptance tests](12-acceptance-and-release.md): mandatory verification and release gates.
7. [Research](13-research-and-provider-readiness.md): evidence, limits, provider readiness.
8. [Gap register](14-gap-resolution-register.md): decisions and remaining external prerequisites.
9. [Phases](07-implementation-phases.md), [UX](09-ui-wireframes.md), [coding brief](10-codex-prompt.md).
10. [Catalog](01-channel-catalog.md), [capabilities](06-capability-matrix.md), [examples](05-routing-examples.md).

The images in [design](design/) remain visual references, not behavioral authority. Updated UX requirements override conflicting controls in those references.

## Scope and readiness

Foundation: core models, governance, mock adapter, safe ingestion, transactional dispatch, blocklist, operations UI and database/security/concurrency tests.
First live slice: Telegram Bot API private text messages, one bot endpoint per account, human-approved outbound; no groups, media, bulk or social publishing in this slice.
Subsequent releases: WhatsApp/Slack/Discord, attachments, business bridges, bulk, social, then optional AI moderation. All twelve channel types remain discoverable as catalog entries, visibly unavailable until their adapter is installed and verified.

No live credentials, webhooks, database configuration, subscriptions or external messages are created by this planning work. Deployment prerequisites do not block foundation coding; they do block live release. See the explicit gates in file 12.
