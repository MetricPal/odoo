# ADR 0011: Messaging Marketing reuses Omnichannel sending with one review per mailing

## Context

Omnichannel is for conversations: every outbound message is one reviewed
`omni.command` with its own Approval Center request, and the dispatch worker
also requires an `omni.consent` record for the recipient. Marketing sends one
text to many opted-in people, like Email and SMS Marketing. One review per
recipient would not work, and bypassing the worker would duplicate its
safety checks (frozen payload, sender generation, retries, unknown-outcome
reconciliation, circuit breaker).

## Decision

A separate app, `messaging_marketing`, owns the audience (contacts, opt-in
evidence per channel, lists, blacklist) and mailings. A mailing is reviewed
once in Approval Center with its text, channel and exact recipient list
frozen and hashed, using the channel's message approval type (same rules as
Omnichannel: assigned approvers, team members, never the requester).

On approval (or at the scheduled time) the mailing queues one ordinary
`omni.command` per recipient for the existing dispatch worker. Omnichannel
gained two overridable steps in `_check_dispatch_authorization`, with
unchanged default behaviour:

- `_approval_targets_command(request)`: a mailing message accepts its
  mailing's review instead of a per-message review. Approver lines, policy
  hash, payload hash, sender generation and expiry are still checked.
- `_check_recipient_authorization()`: a mailing message is authorized by the
  person's current opt-in and the blacklist (`mm.contact._send_refusal`)
  instead of `omni.consent`.

Everything else in the chain still runs (inbox conversation checks, blocked
identities, Telegram sandbox guard). A STOP reply in any inbound WhatsApp or
Telegram conversation records an opt-out with the message as evidence.

## Alternatives considered

- Extend Odoo's Email/SMS Marketing (`mass_mailing`): its sending engine is
  mail/SMS specific and has no per-recipient approval evidence or Omnichannel
  connector path.
- Mailings calling provider APIs directly: duplicates the worker and its
  safety properties, and would bypass the sandbox and certification limits.

## Consequences

- Sending volume and reach are exactly those of the Omnichannel connectors:
  today Telegram sends only to its sandbox allowlist (at most 10 people who
  started the bot), and WhatsApp cannot send (inbound only). Mailings work
  end-to-end within these limits; production broadcasts and WhatsApp template
  messages are separate, explicit decisions.
- Telegram 403 refusals for one chat (bot blocked, account deleted) are now
  `invalid_recipient` instead of `unauthorized`, so one person blocking the bot
  no longer marks the sender unhealthy.

## Status

Accepted (stage 2 of Messaging Marketing).

## Date

2026-10-23
