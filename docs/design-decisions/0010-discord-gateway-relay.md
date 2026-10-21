# ADR 0010: Discord receives through a signed gateway relay

## Context

Discord delivers new messages only over its gateway, a WebSocket connection
that must stay open and send heartbeats. Odoo's request workers are
short-lived and cannot hold it. The plan listed two options (decision 1):
ship a small companion program, or let Hermes Agent's messaging gateway hold
the connection.

## Decision

Ship `omni_discord/tools/discord_relay.py`, a standalone program (requests +
websocket-client) that holds the gateway connection and POSTs each new text
message to the channel's Omnichannel inbound URL. Each batch is signed with
HMAC-SHA256 over `<timestamp>.<body>` using a per-channel relay secret created
in setup; Odoo accepts batches at most five minutes old, for the configured
bot only, and only from direct messages or the server channels chosen in
setup. The relay never sends to Discord: replies are reviewed, approved and
sent by Odoo through Discord's REST API, mentioning only the person answered.

## Alternatives considered

- Hermes Agent's gateway: fits "AI Agent is the control panel for Hermes", but
  ties customer messaging to the AI runtime's availability and gives Hermes
  the bot token. It can be added later as a second relay that signs the same
  way.
- Discord interactions (slash commands over HTTP): no relay, but people would
  have to use commands instead of writing normally.

## Consequences

- One more process to run and monitor next to Odoo; the setup screen shows the
  exact command.
- Messages sent while the relay is down are not replayed (the relay starts a
  fresh session on reconnect).
- Odoo deduplicates by Discord message ID, so relay retries are safe.

## Status

Accepted (plan default; the person can still choose the Hermes option).

## Date

2026-10-21
