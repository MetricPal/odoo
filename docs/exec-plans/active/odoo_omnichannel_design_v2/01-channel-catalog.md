# Channel Catalog

## Messaging Platforms

| Platform | Type | Typical inbound endpoint | Outbound | Main capabilities |
|---|---|---|---:|---|
| WhatsApp Business | Messaging | Phone number / business identity | 1 per module | Private, group where supported, template/bulk, media, replies |
| Telegram | Messaging | Bot, group, channel | 1 per module | Private, group, broadcast, media, bot interactions |
| Slack | Messaging | Workspace/channel/app endpoint | 1 per module | DM, channel conversation, replies, files |
| Discord | Messaging / Community | Bot, server/channel | 1 per module | DM where supported, channels, replies, community messaging |

## Social Platforms

| Platform | Type | Typical inbound endpoint | Outbound | Main capabilities |
|---|---|---|---:|---|
| LinkedIn | Social | Company/Page/account identity | 1 per module | Posts, comments, replies, engagement where API permits, messaging where permitted |
| Facebook | Social | Page/account identity | 1 per module | Page posts, comments, replies, Messenger where permitted |
| Instagram | Social | Business/Creator account | 1 per module | Posts, comments, replies, DM where permitted |
| X (Twitter) | Social | Account identity | 1 per module | Posts, replies, likes/engagement where API permits, DMs where permitted |
| TikTok | Social | Business account | 1 per module | Publishing/engagement capabilities subject to TikTok API permissions |
| YouTube | Social / Video | Channel | 1 per module | Video publishing where permitted, comments, replies, channel activity |
| Threads | Social | Account identity | 1 per module | Posts, replies, engagement where API permits |
| Pinterest | Social / Visual | Business account | 1 per module | Pin publishing and engagement where API permits |

## Explicitly outside this Omni-Channel core

| Platform | Owner |
|---|---|
| Email | Odoo native Email / Email Marketing |
| SMS | Odoo native SMS / SMS Marketing |

These can later have an integration adapter into a unified activity layer without creating duplicate sending engines.
