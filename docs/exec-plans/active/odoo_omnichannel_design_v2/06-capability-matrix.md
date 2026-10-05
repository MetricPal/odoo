# Capability Matrix

This is a logical capability catalog. Actual availability must be validated against each provider's current API, account type, permissions, and policy.

| Capability | WhatsApp | Telegram | Slack | LinkedIn | Facebook | Instagram | X | TikTok | YouTube | Discord | Threads | Pinterest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Receive inbound | Yes | Yes | Yes | API-dependent | Yes/API-dependent | Yes/API-dependent | API-dependent | API-dependent | Yes/API-dependent | Yes | API-dependent | API-dependent |
| Private message | Yes | Yes | Yes | API-dependent | Messenger | DM/API-dependent | API-dependent | API-dependent | Limited/API-dependent | Yes | API-dependent | Limited |
| Group/channel conversation | Supported where applicable | Yes | Yes | Limited | Groups/API-dependent | Limited | API-dependent | Limited | Comments | Yes | Limited | Boards/comments model |
| Bulk/broadcast | Template/policy dependent | Yes | Rate/policy dependent | API/policy dependent | API/policy dependent | API/policy dependent | API/policy dependent | API/policy dependent | API/policy dependent | Bot/channel dependent | API-dependent | API-dependent |
| Publish post | N/A | Channel/bot messages | N/A | Yes/API-dependent | Yes | Yes | Yes | Yes/API-dependent | Yes | N/A | Yes/API-dependent | Yes/API-dependent |
| Comment | N/A | N/A | N/A | Yes/API-dependent | Yes | Yes | Yes/API-dependent | API-dependent | Yes | N/A | API-dependent | API-dependent |
| Reply | Yes | Yes | Yes | API-dependent | Yes | Yes | API-dependent | API-dependent | Yes | Yes | API-dependent | API-dependent |
| Like/reaction | N/A | Reactions/API-dependent | Reactions | API-dependent | Yes/API-dependent | Yes/API-dependent | API-dependent | API-dependent | API-dependent | Reactions | API-dependent | API-dependent |

Do not hard-code this table as permission truth. The runtime must query/configure capabilities for each connected provider account and enforce provider limits.
