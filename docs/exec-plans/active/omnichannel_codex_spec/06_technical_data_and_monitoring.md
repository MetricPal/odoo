# 06 — Technical Data and Monitoring

## PRIMARY UX RULE

Technical fields remain available but are not primary configuration fields.

Examples:
- Provider Message Key
- Attempt Count
- Next Attempt At
- Lease Expires At
- Ownership Version
- Route Key
- Circuit Until
- Raw Provider Response
- Low-level retry state

## WHERE THEY BELONG

Monitoring:
- Health
- Delivery
- Failed Messages
- Activity / Logs

Record details:
Expandable "Technical Details" section.

## MESSAGE DETAIL

Primary:
- Direction
- Channel
- Sender
- Recipient
- Business purpose
- Status
- Created time
- Related business record

Secondary:
- dispatch attempts
- provider message key
- retry state
- provider response
- lease/runtime information

## PURPOSE

Progressive disclosure prevents the UI from looking like an exposed database schema while preserving operational observability.
