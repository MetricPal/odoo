# 03 — Overview Dashboard

## PURPOSE

Overview is an operational control center.

It is NOT a database/model index.

## WHEN CHANNELS EXIST

Show:

### Channel Health
Cards/list:
- Channel
- Type
- Purpose/Team
- Status
- Active outbound sender
- Inbound status

### Needs Attention
Examples:
- Connection failed
- Sender health failed
- Inbound endpoint disabled
- Delivery failures
- Configuration incomplete

### Recent Activity
Examples:
- inbound message received
- outbound message sent
- sender switched
- endpoint verified
- provider connection warning

### Primary action
[ + Add Channel ]

## DO NOT SHOW BY DEFAULT

- provider account IDs
- route keys
- ownership versions
- lease expiry
- raw provider responses
- retry internals
- database record identifiers

These belong in technical details/monitoring.
