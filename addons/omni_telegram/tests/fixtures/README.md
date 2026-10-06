# Synthetic Telegram protocol fixtures

Reviewed against the official [Telegram Bot API](https://core.telegram.org/bots/api) on 2026-10-06; rolling documentation identified Bot API 10.3 (2026-08-24).

`private_text.json` is hand-authored synthetic input, not a recording from a live bot. Its user, bot, text and identifiers are test-only. Tests derive edit, group, media, business, invalid-identity and unsupported-update variants in memory. `FakeHTTP` generates synthetic getMe/getChat/sendMessage envelopes and explicit rejection/unknown responses. The fake token and webhook secret are intentionally non-operational.

Relevant contracts: Update, Message, Chat, User, getMe, getChat, sendMessage, setWebhook secret_token and ResponseParameters.retry_after. The provider's documentation is rolling; refresh fixtures and record live sanitized evidence before sandbox certification. Tests never register a webhook or invoke a real Telegram endpoint.
