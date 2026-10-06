# Research evidence and provider readiness

Checked 2026-10-05. Local source revision: `dbce1c66c4d1f9779f55d82657e8214d2c09654b`. Evidence distinguishes verified source facts, project design choices and unresolved deployment prerequisites. Links are primary sources; no third-party tutorial is implementation authority.

## Odoo source evidence

Paths below are repository-relative:

- `odoo/addons/base/models/ir_access.py`: `ir.access` operation/domain and `_compute_kind`: grouped records grant permission; no-group records restrict. Domain evaluation exposes activated `company_ids`.
- `odoo/orm/models.py`: `check_access` and `has_access` are current access entry points.
- `odoo/orm/table_objects.py`: `Constraint`, `Index`, `UniqueIndex`; partial index definitions supported. Verify generated index name and actual database enforcement in tests.
- `odoo/addons/base/models/ir_cron.py`: `_trigger`, `_commit_progress`; progress commits the transaction and returns remaining runtime. Therefore use only deliberate worker transaction boundaries.
- `addons/payment_stripe/controllers/main.py`: HTTP webhook route with protocol verification, timestamp and constant-time signature comparison. It is an API reference, not permission to copy sensitive logging.
- `addons/bus/models/bus.py`: `_sendone` recommends `bus.listener.mixin` for security. Notifications must not become an alternate data-access channel.
- `addons/approval_center/models/approval_center_request.py`: public action dispatch via target model/record and policy-related action; current checks do not implement the full Omni immutable command contract.
- `addons/approval_center/models/approval_center_audit.py`: audit request relation cascades deletion; not an independently durable execution ledger.
- `addons/approval_center/security/ir.access.csv`: role grants need Omni-specific company/purpose restrictions and mutation tests.
- `addons/social_media/__manifest__.py`: company social configuration, not a full campaign/publishing engine. `mail`, `sms` and `mass_mailing` are present.

Official [Odoo 20 ORM documentation](https://www.odoo.com/documentation/20.0/developer/reference/backend/orm.html) corroborates version-specific ORM APIs. The [Odoo 20 index](https://www.odoo.com/documentation/20.0/genindex.html) lists `_commit_progress`. Direct retrieval of the actions reference failed twice in this research session; cron semantics were verified in local source instead. Do not substitute Odoo 19 documentation for unresolved Odoo 20 behavior.

## Delivery and security research

- [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) explains the database/external-effect dual-write problem and warns that an outbox can still produce duplicates. Project decision: durable command plus explicit unknown outcome and adapter-specific dedup, not a universal exactly-once promise.
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html) documents row locks. Project decision: short claim/selection transactions and independent concurrency tests. Do not claim these locks make an external HTTP call atomic.
- [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) informs destination allowlisting and redirect/address checks. Project adds bounded media retrieval and egress controls.
- [OWASP secrets management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) informs separation, least privilege and lifecycle. Project chooses a secret-reference interface with deployment-provisioned values; a particular commercial vault is not required.

## First live adapter: Telegram

Primary source: [Telegram Bot API](https://core.telegram.org/bots/api), including getMe, setWebhook, Update and sendMessage. Verified identifiers and secret-header verification inform the private-text slice. A successful send returns a message; it is not a delivered/read receipt. The documented sendMessage parameters do not establish a generic client idempotency key, so ambiguous sends must not automatically retry. Bot API documentation is rolling; record exact fixture version/date at adapter implementation and do not borrow MTProto method semantics.

Deployment prerequisites: authorized bot, provisioned token/secret, HTTPS endpoint, verified identity, opted-in test recipient and confirmed webhook setup. No live account was accessed and no real send was tested. Paid/guest/business/group/media features are outside the first slice.

## Other providers

Slack: [request verification](https://api.slack.com/authentication/verifying-requests-from-slack), [Events API](https://docs.slack.dev/apis/events-api/) and [rate limits](https://docs.slack.dev/apis/web-api/rate-limits/) were checked. Verify raw-body signatures and replay freshness; acknowledge durably within the documented three-second limit; deduplicate event IDs. Honor Retry-After. Product scopes and sandbox tests remain adapter-release prerequisites. These references do not establish permission for every messaging operation.

WhatsApp: direct Meta developer overview retrieval failed. Meta's own [Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api) confirms phone-number-ID-addressed messages and account setup. This is enough to identify sender identity as a real routing constraint, not enough to certify current templates, pricing, group support or account eligibility. Refresh official version-specific policy/API evidence and verify the actual account before implementing/enabling those capabilities. No old pricing or broad Yes capability table is carried forward.

Discord and the remaining social channels: catalog only. Current endpoint/scopes/access/transport were not researched to implementation depth in this foundation pass. Each must satisfy the future-adapter gate before coding its transport. This is intentional release scope, not a claim that their APIs have been verified. Core DTOs accommodate later events; any incompatible semantics require an explicit contract extension and tests.

## Defaults versus facts

First-provider choice, approval expiry, retention periods, health TTL, retry/lease limits, load targets and recovery objectives are project engineering decisions, not provider mandates or measured deployment guarantees. They are editable through reviewed policy/configuration with tests. Physical endpoint ownership and single active sender preserve the original product requirements.

## Research completion boundary

Sufficient evidence exists to begin core/mock implementation and the scoped Telegram adapter. Actual credentials, tenant permissions, infrastructure performance, provider app reviews and all future adapters remain release-specific evidence. No document can truthfully certify those in advance; they are tracked as explicit gates rather than hidden assumptions.

## Telegram implementation evidence — 2026-10-06

Refreshed the official [Bot API reference](https://core.telegram.org/bots/api); the rolling page identified Bot API 10.3 dated 2026-08-24. Verified private Chat/User identifiers, Update/Message text and edit fields, getMe/getChat/sendMessage, setWebhook secret_token and ResponseParameters.retry_after. Bot identity checks and the returned message contract inform the implementation; local test fixtures are synthetic, not recordings.

Project choices are stricter than provider-wide capability: one to ten explicitly authorized private recipients, no groups/media/business/guest operations, minimum 32-character webhook secret, tenant-bound secret bundle and deployment networking disabled by default. Live sandbox behavior is still unverified. See [implementation status](18-telegram-sandbox-implementation-status.md) and the linked activation runbook; future-provider readiness is unchanged.
