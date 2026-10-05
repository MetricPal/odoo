# Data Model

## Main entities

### omni.provider
Represents the provider/platform family.

Examples: WhatsApp, Telegram, Slack, LinkedIn, Facebook, Instagram, X, TikTok, YouTube, Discord, Threads, Pinterest.

### omni.account
Represents an authenticated provider account/connection.

Suggested fields:

```text
id
provider_id
company_id
name
external_account_id
credential_reference
status
metadata
```

### omni.channel
Represents the module-level logical channel.

Suggested fields:

```text
id
module_model
module_record_id
provider_id
direction = outbound
name
account_id / sender_reference
status
```

Constraint:

```text
unique(module_model, module_record_id, provider_id, direction=outbound)
```

### omni.inbound.endpoint
Represents an actual receiving address/account/bot/page/number.

Suggested fields:

```text
id
provider_id
account_id
external_endpoint_id
endpoint_type
name
module_model
module_record_id
status
webhook_config
metadata
```

Constraint:

```text
unique(provider_id, external_endpoint_id)
```

### omni.identity
Maps an external identity to an Odoo contact.

```text
id
partner_id
provider_id
external_identity_id
handle
phone/email if appropriate
metadata
```

A single Odoo contact may have many identities.

### omni.conversation
Provider-independent conversation abstraction.

```text
id
provider_id
channel_id / endpoint_id
partner_id
external_conversation_id
module_model
module_record_id
state
assigned_user_id
last_message_at
```

### omni.message
Provider-independent message/event representation.

```text
id
conversation_id
provider_id
external_message_id
direction
message_type
body
sender_identity_id
recipient_identity_id
status
sent_at
received_at
metadata
```

### omni.capability
Declares what an account/endpoint can do.

```text
provider_id
account_id
capability_code
enabled
constraints
```

### omni.routing.rule
Controls inbound event routing and module association.

```text
provider_id
endpoint_id
module_model
module_record_id
priority
active
```

## Relationship overview

```text
Business Module
      │
      ├─────────────── 1 ────────────────┐
      ▼                                  ▼
Logical Outbound Channel            N Inbound Endpoints
      │                                  │
      ▼                                  ▼
Sender / Account                    External Address
      │                                  │
      └──────────── Provider ────────────┘
                         │
                         ▼
                    Conversations
                         │
                         ▼
                      Messages
                         │
                         ▼
                    Odoo Contacts
```
