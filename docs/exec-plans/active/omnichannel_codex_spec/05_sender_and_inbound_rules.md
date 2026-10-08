# 05 — Sender and Inbound Rules

## OUTBOUND

Allowed:
- Multiple configured senders.

Required:
- Exactly one active sender at runtime per Channel + Business Purpose.

Activation algorithm:

1. User selects sender.
2. System runs health check.
3. If PASS:
   - activate selected sender
   - deactivate previous sender
4. If FAIL:
   - do not activate selected sender
   - keep previous active sender unchanged
   - show failure reason

Never allow two active runtime senders.

## INBOUND

Allowed:
- Multiple active inbound endpoints for one Channel + Business Purpose.

Each endpoint must have:
- receiving identity
- channel
- business purpose/team
- active state
- health/verification state

## INBOUND PROCESSING ORDER

1. Provider receives event.
2. Validate endpoint/provider.
3. Resolve receiving identity.
4. Evaluate blocklist.
5. Resolve business purpose/routing.
6. Create/process business event.

A blocked identity must not enter normal business processing.
