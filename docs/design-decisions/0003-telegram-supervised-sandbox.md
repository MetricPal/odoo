# ADR 0003: Telegram as an explicitly authorized private-text sandbox

Date: 2026-10-06. Status: accepted for sandbox implementation; live certification pending.

## Context

The transport-neutral inbox and dispatch worker are verified. The first provider must preserve their company/team, approval, identity continuity and unknown-outcome contracts without treating installation or inbound activity as sending permission.

## Decision

Ship Telegram in optional `omni_telegram`. Limit it to one bot namespace, private-text/edit input and human-approved replies to one to ten explicitly listed test users. Require deployment networking permission, a database/company/bot-bound secret bundle, manager authorization evidence, an active intake policy/endpoint, current consent and per-message approval. Scheduler activation and external webhook registration remain separate human-controlled operations.

Use getMe and getChat as bounded read-only preflights and sendMessage once per claim. Successful response identity/text must match the claim. Store a bot/chat/message composite key. Treat timeout, malformed success and server errors as unknown; explicit rate-limit rejection can use the worker's bounded retry contract. Never infer delivery/read state or provider-side idempotency.

Move sender health I/O ahead of selection locks, then recheck configuration versions, active flags and generation under the existing company/channel guard. Carry only non-secret adapter metadata in immutable claims. Maintain the existing company → channel → command lock order and committed-claim transport boundary.

Use fixed-host, verified HTTPS with pinned public DNS resolution, no proxy/redirect/retry behavior, body and time budgets, and sanitized errors. Provision secrets outside Odoo with exact tenant bindings. The trusted adapter registry is process-local; scope metadata and secret binding prevent cross-database credential use even when code is loaded for another registry.

## Consequences

Installation remains inert. Authorization can be revoked without pretending to recall an in-flight send. Configuration rotation requires revocation and reverification. The addon contains no automatic setWebhook capability, preventing a connection button from silently replacing existing provider setup.

Synthetic protocol fixtures and mocked HTTP prove local contracts but do not certify actual provider behavior or deployment operations. Live sandbox and production gates remain explicit. Concurrent edits sharing the same timestamp quarantine conflicting content; no guessed ordering is applied. A deployment-level secret administrator remains a trusted privileged actor.

See [implementation and tests](../exec-plans/active/odoo_omnichannel_design_v2/18-telegram-sandbox-implementation-status.md) and [operator runbook](../../addons/omni_telegram/README.md).
