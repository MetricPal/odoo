# Capability model and release matrix

Catalog presence is not a capability grant. Effective permission is the intersection of installed adapter support, verified account scope, sender/endpoint grant, current provider restrictions, company/purpose policy, user/business access and approval. Unknown or expired evidence denies execution. Check on preparation and immediately before dispatch.

Codes: `message.receive`, `message.send`, `conversation.reply`, `message.bulk_send`, `group.send`, `media.upload`, `social.post`, `social.comment`, `social.reply`, `social.reaction`, `social.delete`. New codes require a versioned normalized schema and acceptance tests.

| Channel | First release status | Enablement requirement |
|---|---|---|
| Telegram | First live adapter: private text receive/send/reply | verified bot ID, secret webhook, recipient eligibility, active sender, approved command |
| WhatsApp Business | Deferred, catalog only | current Cloud API version, real account/scopes, number ownership, webhook verification, templates/window/consent rules |
| Slack | Deferred, catalog only | workspace/app scopes, signed requests, event dedup, rate handling |
| Discord | Deferred, catalog only | transport decision (Gateway versus interaction endpoint), intents/scopes and connection lifecycle |
| LinkedIn | Deferred, catalog only | product access and operation-specific permissions |
| Facebook | Deferred, catalog only | Page permissions and operation-specific review |
| Instagram | Deferred, catalog only | eligible account and operation-specific permissions |
| X | Deferred, catalog only | API tier and permitted operations |
| TikTok | Deferred, catalog only | product/app review and publishing capabilities |
| YouTube | Deferred, catalog only | OAuth scopes, quota and supported operations |
| Threads | Deferred, catalog only | verified current API operations/scopes |
| Pinterest | Deferred, catalog only | verified current API operations/scopes |

The previous broad Yes/API-dependent matrix is removed: it was a planning catalog, not verified provider capability evidence. In particular, do not infer group messaging, direct messaging, receipt tracking or bulk support from a provider's name.

Grant constraints include content size/type, recipient eligibility, reply identity, thread requirements, current time window, template/language/version, scope expiry, API version and documented rate bucket. Administrative configuration may disable support but cannot invent adapter support.
