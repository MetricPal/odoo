# Core Business Rules

## 1. Outbound cardinality

For each business module and channel type there is exactly one logical outbound channel.

```text
UNIQUE(module_id, channel_type, direction=OUTBOUND)
```

Examples:

```text
Marketing + WhatsApp = 1 outbound
Marketing + Telegram = 1 outbound
Marketing + LinkedIn = 1 outbound
Sales + WhatsApp = 1 outbound
```

## 2. Inbound cardinality

For each business module and channel type there can be many inbound endpoints.

```text
(module_id, channel_type, direction=INBOUND) = 1..N endpoints
```

Example:

```text
Marketing + WhatsApp
  +60111111111
  +60122222222
  +60133333333
```

## 3. Endpoint ownership

One inbound endpoint can belong to only one business purpose/module at a time.

```text
UNIQUE(provider, external_endpoint_id)
```

Therefore the same WhatsApp number, Telegram bot, Facebook Page, Instagram account, etc. cannot simultaneously be assigned to Marketing and Sales.

## 4. Purpose is explicit

Every inbound endpoint must have a `purpose/module_id` before it can receive production traffic.

Examples:

```text
WhatsApp +60111111111 -> Marketing
WhatsApp +60122222222 -> Sales
Telegram Bot A         -> Recruitment
LinkedIn Page A        -> Marketing
```

## 5. Outbound sender abstraction

The logical outbound channel is not necessarily a physical phone number or account record. It is the module's canonical sender route for that provider.

It may reference one active sender identity today and support provider-specific sender pools internally later, without changing the module-level API.

## 6. No channel duplication by module

A module should not need to know provider-specific APIs. It asks the Omni service to perform an operation against its logical channel.

Example:

```text
Marketing -> WhatsApp -> send_message(...)
```

The provider adapter handles authentication, API format, rate limits, retries, and delivery state.

## 7. Capability-driven behavior

Never assume all providers support the same operations. Capabilities are declared per provider/account/endpoint.

Examples:

- `message.send`
- `message.receive`
- `message.bulk_send`
- `conversation.create`
- `conversation.reply`
- `group.send`
- `social.post`
- `social.comment`
- `social.reply`
- `social.like`
- `social.reaction`
- `media.upload`

The UI and service layer must check capabilities before exposing or executing an operation.

## 8. Human approval

Any operation that changes external or organizational state must support the platform's explicit approval layer.

Examples requiring approval according to the project's governance model:

- send outbound message
- bulk/broadcast send
- publish social post
- comment/reply
- like/reaction
- create or modify an external campaign/action

AI agents can prepare the action, but execution must pass through approval.
