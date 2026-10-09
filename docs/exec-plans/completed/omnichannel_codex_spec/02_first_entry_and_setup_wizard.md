# 02 — First Entry and Generic Setup Wizard

## FIRST ENTRY

Condition:
No Omni-Channel has been configured.

Render:

Welcome to Omni-Channel

Connect your communication channels and make them available to your teams.

[ + Add Channel ]

Setup progress:
1 Channel
2 Connection
3 Inbound
4 Outbound
5 Verify
6 Activate

Do not render raw configuration records on this first-entry screen.

## ADD CHANNEL WIZARD

### Step 1 — Choose Channel

Present channel categories and an extensible provider catalog.

Messaging:
WhatsApp
Telegram
Slack

Social:
Instagram
Facebook
LinkedIn
X
TikTok
Threads
YouTube

The catalog must be data-driven/extensible. Do not hardcode Telegram-specific business logic.

### Step 2 — Connection

Fields:
- Display Name
- Channel Type
- Provider Account
- Business Purpose / Team
- Company

Credentials/secrets:
- Securely stored
- Masked after creation
- Never exposed as plain text

### Step 3 — Inbound

If inbound is supported:
- Enable receiving
- Receiving identity
- Business purpose/team
- Endpoint status
- Verify

A receiving identity belongs to one purpose.

### Step 4 — Outbound

Show available sender identities.

Multiple senders may be configured.

Exactly one sender can be active for runtime outbound.

Use radio/single-select semantics.

### Step 5 — Verify

Run:
- Connection check
- Inbound verification
- Outbound sender health check

Display actionable results.

### Step 6 — Activate

Activation is blocked if required checks fail.

On success:
- activate
- show success
- return to Channel detail or Overview

The wizard ends after activation.

## AFTER FIRST SETUP

The normal Overview replaces onboarding.

The Add Channel button remains available.
