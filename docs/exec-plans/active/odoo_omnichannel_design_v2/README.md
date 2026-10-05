# Odoo Omni-Channel Architecture

## Scope

This package defines a reusable Omni-Channel core for an Odoo Community-based platform.

The Omni-Channel layer covers external messaging and social platforms while integrating with Odoo business modules such as Marketing, Sales, Recruitment, HR, and future custom modules.

### Explicit boundary: Email and SMS

Odoo already has native Email Marketing and SMS Marketing capabilities. Therefore this Omni-Channel design does **not** create a second Email Marketing or SMS Marketing engine.

- Email marketing remains managed by Odoo's native Email Marketing / mail infrastructure.
- SMS marketing remains managed by Odoo's native SMS Marketing infrastructure.
- Omni-Channel may expose integration hooks or unified activity/conversation views later, but it does not duplicate their campaign/sending engines.

Odoo's current documentation confirms dedicated Email Marketing, SMS Marketing, and Social Marketing applications. The custom Omni-Channel is therefore focused on the cross-channel capabilities and routing rules not intended to be duplicated inside those native apps.

## Core rule

For every `Business Module + Channel Type` combination:

- exactly **one logical Outbound Channel**;
- **one or many Inbound Endpoints**;
- each Inbound Endpoint belongs to exactly **one Business Purpose / Module**.

Example:

```text
Marketing
  WhatsApp
    Outbound: 1
    Inbound: N

  Telegram
    Outbound: 1
    Inbound: N

  LinkedIn
    Outbound: 1
    Inbound: N
```

## Design principle

**One outbound logical channel, many inbound endpoints.**

The outbound object represents the business module's logical sender for a provider. Inbound endpoints represent the actual addresses/accounts/numbers/bots/pages through which messages or events enter the system.

## Outbound Sender Pool Clarification

Outbound is **multiple in configuration, single in runtime**:

`Module + Channel -> Outbound Sender Configurations (N) -> Active Sender (0..1)`

The active sender is selected with a radio-button-style UI and must pass a real provider health check before activation. No automatic failover is allowed.


# Design
Design mock screens are stored in [`design/`](design/).
