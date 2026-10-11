# Social

A separate workspace for incoming social activity and approved publishing.
Install `omni_instagram` and/or `omni_linkedin`, then open **Social → Accounts**.

1. Choose the platform, team and approval type; connect the account.
2. **Sync activity** imports the latest supported posts, comments and private text.
3. Create a post or reply, then **Submit for approval**.
4. An assigned, different team member reviews the exact content in Approval Center.
5. **Publish / send** executes the approved action once.

Choose a format and add files in order. Approval shows the exact files and order.
Instagram uses the account’s public HTTPS address for expiring media URLs.
Publish prepares media automatically and resumes saved IDs if processing is pending.

| Connector | Incoming | Outgoing |
|---|---|---|
| Instagram | Latest posts/reels, active stories, comments, engagement counts, private text | Photos, mixed carousels, reels, business-only stories; public/private text replies |
| LinkedIn company Page | Permitted posts, comments, engagement counts | Public text/image/multi-image posts and replies |
| LinkedIn personal profile | Same reads only with approved restricted access | Public text/image/multi-image posts and permitted replies |

Sync is manual or triggered by signed webhooks, and bounded: latest 20 posts/chats, up to 50 comments per post and
25 messages per Instagram chat, with a time limit. The account reports unavailable
read access. It does not scrape data or bypass app approval. LinkedIn private
messages, LinkedIn stories/reels, private media replies, ads, full analytics and scheduled
publishing are not implemented in this version.

Private Instagram replies require manager-confirmed recipient agreement, a fresh
incoming message within 24 hours and separate approval. Revocation and the existing
Omnichannel blocked-identity ledger apply. Block using the Instagram channel type,
account ID as namespace, and received sender ID. Imported private content from a
blocked sender is suppressed.

Activity snapshots expire under the account's 1–365 day retention policy, applied
by the daily retention job and sync. Frozen approval/publication evidence is
retained separately, including the reviewed target content. Review expires after
24 hours. Credential/configuration changes invalidate pending reviews. Uninstalling
a provider archives its accounts and keeps review history.

Secrets live in encrypted, scoped private files under Odoo's data directory;
back up that directory with the database. Tokens never become editable ORM fields.
Publishing commits an audited claim before I/O. Publishing/unknown attempts cannot
repeat. No outbound cron or automatic retry is enabled. Provider acceptance is
reported as acceptance, not proof of audience delivery. A crashed in-flight claim
requires checking the platform; no unsafe reset button is offered.

No Omnichannel, Telegram, WhatsApp, Slack or Teams source files are changed.

Media limits: JPEG under 8 MB, MP4 under 64 MB (H.264/HEVC, 23–60 fps). Reels
are 3–900 seconds; story/carousel videos 3–60 seconds. Instagram carousels use
2–10 files; LinkedIn uses 2–20 photos. Stories have no caption. `ffprobe` is required.
LinkedIn image publishing requires permission to read asset ownership/status.

For webhooks, set the public HTTPS address, enter **App secret**, then configure.
Register the shown callback in the developer portal; Meta also needs the shown
verify token and selected fields. LinkedIn requires approved webhook access and
a Page social-action event subscription. These registrations are external. The
receiver verifies signatures, deduplicates, and queues account-scoped read-only
sync each minute. It does not dispatch or infer private-message agreement.
Webhook hints coalesce bounded snapshots, not a full event/deletion archive.
Callbacks are account-scoped: use a dedicated app/subscription for each account
when the platform provides only one callback per app. Disable stops local receiving; remove external subscriptions in the portal.
Live delivery and publishing still need account-based verification.
