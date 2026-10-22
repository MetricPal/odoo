# Social

Incoming social activity and approved publishing, under the **Social** app
menu (Activity, Publishing, Accounts). Install a connector such as
`omni_instagram` or `omni_linkedin`; it pulls in this module.

## Connecting an account

**Accounts › Add account** shows a card per platform. **Connect** opens a short
guided setup: platform and team, connect, who approves (an approval type with
named approvers from the same team; "New approval type" creates one), optional
webhooks, and a final check with **Sync activity now** and **Write the first
post**. An unfinished account shows **Continue setup**.

Platforms that support sign-in show **Sign in with …**: an account manager
enters the developer app's ID and secret once, adds the shown redirect URL to
the app, then signs in on the platform and returns to the account. The app
secret and tokens are kept in the encrypted vault; tokens with an expiry are
refreshed shortly before they lapse without voiding pending reviews. **Paste an
access token instead** remains available.

## Platform rules and usage

Each connector declares its rules in code (`providers/capabilities.py`):
allowed actions and formats, character and media limits, daily caps and, for
paid APIs, the price per action. The account shows them as one line, and
submitting content that breaks them names the platform's limit. Every published
or uncertain action is recorded; daily caps and the monthly budget (paid
platforms only) are checked before the first platform call of an approved post.

1. Add the account (guided setup): platform, team, connection, approvers.
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
messages, LinkedIn stories/reels, private media replies, ads and full analytics
are not implemented in this version.

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

## Writing a post

The post form guides the author with the chosen account's own rules:

- **Account**, **What do you want to do?** and **Format** are picture cards.
  Only the actions and formats the account's platform supports are shown, each
  with a short explanation (for example "2–10 photos or videos people swipe
  through").
- **Text** shows a live character count against the platform's limit (posts,
  replies and private replies can differ). Stories have no text.
- **Photos and videos** is a drop zone that lists the limits for this account
  and format: how many files, which kinds, size, megapixels, video length and
  width. PNG and WebP photos are converted to JPEG in the browser, and very
  large photos are scaled down. Thumbnails show dimensions, size and length;
  files the current account or format does not take are marked.
- **Preview** shows the post the way the platform lays it out (Instagram,
  Facebook, LinkedIn, X, Threads, TikTok, YouTube, Pinterest, stories and
  reels, public and private replies). It is approximate: each platform has the
  final say.
- **Note for the approver** (formerly "Reason") is sent with the approval
  request and is not published.

The server checks the same rules again on **Submit for approval**.
Connectors declare them in `Capabilities` (`format_media`, `photo_bytes`,
`reply_limit`).

## Planning

**Publishing** is a board by stage, with calendar and list views. Give a post a
**Publish at** time to schedule it: the approver sees the time as part of the
content; once approved, it publishes automatically when due (checked every five
minutes) as the person who wrote it. Submit at most 14 days ahead. Without a
time, publish by hand after approval.

**Campaigns** post one message to several accounts of a team: write the text
once, **Create versions**, adapt each version, **Submit all for approval**. A
reviewer can **Approve all** versions assigned to them; each version keeps its
own approval record.

## Inbox and report

**Activity** opens on what still needs an answer. Assign a comment or message
to yourself, mark it **No reply needed**, or reply; a published reply marks it
**Replied**. **Report** shows posts published, likes, comments and received
comments and messages per account and week. With AI Agent installed,
`social_ai` adds drafting and activity summaries; with AI Home, `social_home`
lists what to answer on Home.

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
