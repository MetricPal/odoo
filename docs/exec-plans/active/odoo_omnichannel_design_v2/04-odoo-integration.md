# Odoo Integration Boundary

## Goal

Build Omni-Channel as a reusable Odoo Community module/service boundary rather than embedding WhatsApp/Telegram/social logic separately inside Marketing, Sales, Recruitment, or HR.

## Odoo modules remain owners of business records

Examples:

```text
Marketing -> campaigns, leads, marketing activities
Sales -> leads, opportunities, quotations
Recruitment -> applicants, jobs
HR -> employees/activities
```

Omni-Channel owns communication transport and routing, not the business record itself.

## Recommended integration API

A module should be able to request operations using a provider-neutral interface:

```python
omni.send_message(
    module="marketing",
    channel="whatsapp",
    recipient=identity,
    content=content,
)
```

For inbound:

```python
omni.handle_inbound_event(event)
```

The inbound router resolves:

```text
provider
  -> account
  -> endpoint
  -> endpoint's module/purpose
  -> contact identity
  -> conversation
  -> business record/activity
```

## Provider adapters

Keep provider-specific code isolated:

```text
omni_channel/
  providers/
    whatsapp/
    telegram/
    slack/
    linkedin/
    facebook/
    instagram/
    x/
    tiktok/
    youtube/
    discord/
    threads/
    pinterest/
```

Each adapter should implement only the capabilities supported by that provider/API version.

## Email and SMS boundary

Do not create:

```text
omni.email_marketing
omni.sms_marketing
```

as competing campaign engines.

Instead, if a future unified inbox/activity view is desired, add adapters such as:

```text
Odoo Email -> Omni Activity/Conversation bridge
Odoo SMS   -> Omni Activity/Conversation bridge
```

The source of truth for sending email/SMS remains Odoo's native applications/services.

## Social Marketing boundary

Odoo already provides Social Marketing functionality for several platforms, including Facebook, Instagram, LinkedIn, Twitter/X, and YouTube in its documented Social Marketing application. The custom Omni layer should not blindly duplicate every native feature. It should provide the normalized cross-channel architecture, routing, inbound endpoint ownership, provider adapters, conversation model, and additional capabilities required by the product.

Where a native Odoo feature is sufficient, integrate with it rather than maintaining two independent implementations.
