# Marketing: consent and preferences

One consent record per person and channel (email, SMS, WhatsApp, Telegram, social private messages), in the
spirit of a permission vault.

- **Ledger**: every opt-in and opt-out is a new record with its source (form, preference page, unsubscribe
  link, keyword reply, Messaging, staff, import, data request) and evidence; records cannot be changed or
  deleted. The current status per channel and topic is the latest record.
- **Effective everywhere**: an opt-out reaches the email blacklist (Email Marketing), the phone blacklist
  (SMS) and Messaging consents (WhatsApp, Telegram); marketing workflows also check the ledger. Changes made
  in those apps (unsubscribe links, blacklisting, Messaging opt-ins and STOP replies) come back into the ledger.
- **Preference page**: `/marketing/preferences/<token>` lets the person choose channels and topics or
  unsubscribe from everything; each change is recorded with IP and browser as evidence. Managers open it
  from the person's form.
- **Data requests**: a copy (JSON file) or an erasure (contacts anonymized and archived, addresses kept
  suppressed, history kept anonymized as proof). Both run only after approval (Approval Center type
  *Marketing data request*).
- On install, existing Messaging consents and email blacklist entries are brought into the ledger.
