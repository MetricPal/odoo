# 01 — Information Architecture

## AUTHORITATIVE NAVIGATION

Omni-Channel
- Overview
- Inbox
- Messages
- Channels
- Monitoring
- Configuration

Configuration
- Channels
- Connections
- Senders
- Inbound Endpoints
- Routing
- Policies
- Blocklist

Monitoring
- Health
- Delivery
- Failed Messages
- Activity / Logs

## REMOVE

Remove:
- Start here as a permanent primary destination after onboarding
- Advanced Configuration
- Any top-level menu that exposes a low-level runtime model
- Any Telegram-specific top-level architecture

## TECHNICAL PLACEMENT

Omni-Channel administration is technical infrastructure. In Odoo 20 Community, technical administration belongs with Odoo's Technical settings for administrators/developers. Odoo documents Technical as an area for advanced database settings and developer tools. 

The business-facing Omni-Channel UI must remain clean even when the underlying implementation has many technical models.

## MODEL/NAVIGATION RULE

Never map every model to a menu.

Models are implementation.
Navigation is product architecture.
Views are user experience.

One navigation destination can aggregate multiple models.
