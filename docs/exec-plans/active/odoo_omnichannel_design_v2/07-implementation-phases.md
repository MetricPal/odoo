# Suggested Implementation Phases

## Phase 1 — Core

1. `omni.provider`
2. `omni.account`
3. `omni.channel` (one outbound per module/provider)
4. `omni.inbound.endpoint` (many per module/provider)
5. ownership and uniqueness constraints
6. capability model
7. provider-neutral message service
8. inbound router
9. audit and delivery status

## Phase 2 — Messaging

Implement:

- WhatsApp Business
- Telegram
- Slack
- Discord

Capabilities:

- private message
- group/channel message
- inbound webhook/event
- attachments
- conversation history
- bulk/broadcast where provider permits

## Phase 3 — Social

Implement:

- LinkedIn
- Facebook
- Instagram
- X
- TikTok
- YouTube

Then:

- Threads
- Pinterest

Capabilities are enabled only when supported by the connected provider/API.

## Phase 4 — Odoo business integration

Connect Omni events to:

- Marketing
- CRM/Sales
- Recruitment
- HR
- Contacts
- Activities
- Campaigns

## Phase 5 — Unified UI

Provide:

- Channels
- Accounts
- Inbound Endpoints
- Conversations
- Messages
- Provider status
- Capabilities
- Routing
- Audit
- Approval queue

## Phase 6 — Agent integration

AI agents use Omni-Channel as a tool layer.

The agent can:

1. inspect available channels;
2. prepare a message/post;
3. select a logical outbound channel;
4. create an approval request;
5. execute only after explicit approval.

The agent must not bypass the approval layer.
