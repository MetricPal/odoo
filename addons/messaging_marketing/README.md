# Messaging Marketing

Marketing campaigns over chat apps, alongside Email Marketing, SMS Marketing
and Social Marketing. Built on Omnichannel: its channels send the messages,
through the same approval and dispatch checks as every other message
([ADR 0011](../../docs/design-decisions/0011-messaging-marketing.md)).

## Audience

- **Contacts** (Audience > Contacts): a WhatsApp number (stored in
  international format; local numbers use the contact's or company's country)
  and, for Telegram, the bot conversation the person started. One contact per
  number per company. **Add from Contacts** creates them from Odoo contacts
  with a phone number; **Add to Messaging Marketing** on an Omnichannel
  conversation adds the person who wrote to you.
- **Opt-in per channel, with evidence.** *Record opt-in or opt-out* stores
  who recorded it, when, how the person agreed (form, in person, message,
  keyword, import, request) and the proof. Records cannot be edited or
  deleted; a new one replaces the status. Adding a contact never opts it in.
- **STOP replies**: a WhatsApp or Telegram message that is only "STOP",
  "STOP ALL", "UNSUBSCRIBE" or "BERHENTI" records an opt-out automatically,
  with the message as evidence.
- **Lists** belong to a communication team (Marketing by default); only team
  members see them. A member can leave one list without opting out of
  everything.
- **Blacklist** (Configuration): a number or chat that never receives
  marketing, whatever its opt-in says. Any user can add; only an
  administrator can remove.

A person receives a mailing only when the contact is active, has an address on
the channel, is opted in there, is not blacklisted, and (Telegram) has started
the bot.

## Mailings

1. **Write** (Mailings > New): title, channel (WhatsApp or Telegram), the
   Omnichannel channel to send from, lists, and the message. `{first_name}`
   and `{name}` personalise it. The form shows how many people can receive it
   now and why the others are not included, a character counter against the
   channel limit, a chat-style preview for one recipient, and for WhatsApp an
   optional cost estimate (price per message × recipients).
2. **Submit for approval**: the text, channel and the exact list of
   recipients are frozen. Links become tracked short links first (when Odoo
   has a public HTTPS address), tagged with the campaign, the mailing as
   source and the channel as medium. The review uses the channel's message
   approval type: assigned approvers from the team, never the person who
   prepared it. The approver sees the exact text, the text as one recipient
   sees it, the lists, the number of recipients, who is excluded, the
   schedule and the cost estimate.
3. **Send**: right after approval, or at the chosen time (a scheduled job
   checks every 5 minutes). One Omnichannel message is queued per recipient.
   People who opted out or were blacklisted since the review are skipped.
   The dispatch worker checks each message again just before sending.
4. **Results**: Recipients, Sent, Not sent (with the reason), Skipped and Link
   clicks on the mailing; Reporting > Delivery results across mailings.

A submitted mailing cannot be edited: **Duplicate to change** starts a new
draft. **Cancel mailing** withdraws messages not yet handed to the provider.

## Current limits

Sending is limited by the Omnichannel connectors, by design:

- **Telegram** sends only to the channel's sandbox allowlist (up to 10 people
  who started the bot) until production release.
- **WhatsApp** cannot send yet (the connector only receives). Meta requires
  approved message templates for marketing; template sending is a separate
  step.
- **Sending is paused** on a channel until an Omnichannel administrator
  enables it; approved messages wait.

Access: *Messaging Marketing / User* (implies Omnichannel Operator) and
*Administrator*. Contacts, opt-ins and the blacklist are shared within a
company; lists, mailings and results are limited to their team.
