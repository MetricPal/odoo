# Social

A separate workspace for incoming social activity and approved publishing.
Install `omni_instagram` and/or `omni_linkedin`, then open **Social → Accounts**.

1. Choose the platform, team and approval type; connect the account.
2. **Sync activity** imports the latest supported posts, comments and private text.
3. Create a post or reply, then **Submit for approval**.
4. An assigned, different team member reviews the exact content in Approval Center.
5. **Publish / send** executes the approved action once.

Instagram photos use a public HTTPS server address. Upload a JPEG; the approved
photo is served to Meta through an expiring token URL. If processing is pending,
Publish resumes that same container without uploading a second photo.

| Connector | Incoming | Outgoing |
|---|---|---|
| Instagram | Latest posts, comments, engagement counts, private text | Single JPEG photo with caption; public/private text replies |
| LinkedIn company Page | Permitted posts, comments, engagement counts | Public text posts and replies |
| LinkedIn personal profile | Same reads only with approved restricted access | Public text posts and permitted replies |

Sync is manual and bounded: latest 20 posts/chats, up to 50 comments per post and
25 messages per Instagram chat, with a time limit. The account reports unavailable
read access. It does not scrape data or bypass app approval. LinkedIn private
messages, reels/stories/carousels, attachments, ads, full analytics and scheduled
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
