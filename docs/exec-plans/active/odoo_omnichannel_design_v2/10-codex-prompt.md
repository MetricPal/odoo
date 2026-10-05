# Codex Prompt

You are implementing an Odoo 20 Community module called `omni_channel`.

Read every file in this specification package before writing code, especially:
- 01-channel-catalog.md
- 02-core-rules.md
- 03-data-model.md
- 04-odoo-integration.md
- 06-capability-matrix.md
- 08-codex-implementation-spec.md
- 09-ui-wireframes.md

Implement the module incrementally and keep the code production-oriented.

Mandatory architecture rule:
For each Business Module + Channel Type there can be exactly one logical OUTBOUND configuration and zero-to-many INBOUND ENDPOINTS. Inbound endpoints are individually owned by exactly one business purpose/module. Never model inbound as a second outbound pool.

Example:
Marketing + WhatsApp = 1 outbound + N inbound numbers.
Marketing + Telegram = 1 outbound + N inbound bots/endpoints.
Marketing + LinkedIn = 1 outbound + N inbound/account endpoints where provider semantics permit.

Email and SMS are NOT implemented as new messaging engines. Odoo's native Email Marketing and SMS Marketing remain authoritative. Only build integration hooks if needed later.

Supported channel catalog must be extensible and initially include:
WhatsApp, Telegram, Slack, Discord, LinkedIn, Facebook, Instagram, X, TikTok, YouTube, Threads, Pinterest.

Use provider adapter interfaces. Do not put provider-specific HTTP/API logic in core models.

Build:
1. manifest and module structure
2. models and ORM constraints
3. security groups/access CSV/record rules
4. provider adapter abstractions and mock provider
5. inbound webhook/event pipeline
6. outbound service pipeline
7. conversation/message/participant normalization
8. capability model
9. delivery/retry/idempotency support
10. list, kanban, form, search, action and menu XML views
11. dashboard/reporting views
12. automated tests
13. demo/test data only where safe and clearly marked

Do not invent real API credentials or pretend unsupported provider features work. Add clear adapter TODOs for credentials and provider-specific implementation.

Before finishing, verify:
- module installs cleanly
- XML validates
- Python tests pass
- one-outbound constraint works
- multiple-inbound works
- endpoint exclusive ownership works
- company isolation works
- unsupported capabilities are rejected
- duplicate webhook is ignored safely
- failed outbound can retry without duplicate successful send
- UI clearly shows 1 outbound / N inbound

## Critical Outbound Sender Rule

Do NOT model outbound as a single configuration record. For every `Module + Channel Type`, allow **N configured outbound senders but at most one active runtime sender**.

The admin must select the active sender with a radio-button-style UI. Before activation, call the provider adapter's health-check operation. If unhealthy, do not activate and do not change the current active sender. Normal outbound workflows must always resolve the active sender and must never bypass it to use an inactive sender.

Enforce the one-active rule at database level and protect concurrent activation transactionally. Do not implement automatic failover. If the active sender later becomes unhealthy, mark it unhealthy, block outbound, notify the administrator, and require explicit activation of another sender after a health check.

## Critical Requirement: Inbound Blocklist and AI Moderation

Implement an Inbound Blocklist Layer. A blocked external identity must be stopped before normal conversation, CRM, workflow, notification, or AI processing. Default scope is Module + Channel + External Identity, with optional explicit Global scope.

Add normalized identity handling, block/unblock, reasons/categories, audit events, and a Blocked Identities UI. Add an Inbound Moderation Agent/service that can classify messages and recommend allow/flag/review/recommend_block. The AI MUST NOT automatically execute a block by default; explicit human approval is required.

Required pipeline: `provider webhook -> verify -> normalize identity -> block check -> endpoint/module routing -> conversation/workflow/AI`.

Provider-level blocking is optional and adapter-based. Local Omni blocking must work regardless of provider support. Test blocked sender rejection before conversation creation, module-scoped isolation, global blocking, unblock, AI recommendation approval, and audit trail.
