# Live checks

Automated tests use synthetic platform answers. Before a platform is called
ready, run these checks once with a real test account and record the result
below. Use a test Page or profile with no audience: every check publishes
something.

## Before you start

- A public HTTPS address for Odoo (set it on the account; sign-in returns
  there and platforms fetch approved media from it).
- Two people in the account's team: one writes, one approves.
- An approval type with that approver (the setup's "New approval type").

## Checks (each platform)

| # | Check | Expected |
|---|---|---|
| 1 | Accounts › Add account › Connect, follow the setup | Each step explains what is missing; "Ready" at the end |
| 2 | Save the app ID/secret, add the shown redirect URL to the developer app, **Sign in with …** | Returns to the account, "Connected as <name>" |
| 3 | **Sync activity** | Latest posts and comments appear under Activity; comments are "New" |
| 4 | New post (text only), submit, approve as the other person, **Publish / send** | Published; the platform shows the post; Report counts it next week |
| 5 | Post with one photo | The platform shows the photo; Instagram fetched it from the public address |
| 6 | Reply to a comment from Activity | Published; the comment becomes "Replied" |
| 7 | Post with **Publish at** in 10 minutes | Stays "Scheduled", then publishes within 5 minutes of the time |
| 8 | Change the account's approval type while a post waits for review | The review is voided; publishing asks for a new review |
| 9 | Webhooks: enter the app secret, register the callback | A new comment arrives within a minute without Sync |
| 10 | Wait past the token expiry (or revoke and sign in again) | Publishing still works after refresh, or asks to sign in again |

Facebook also: 2–10 photos in one post, a video, a reply to a comment.
Threads also: a carousel, a video (waits for processing), the 250-a-day counter.
Pinterest: checks 3, 6 and 9 do not apply (no comments API); also a 3-image Pin with a link.
TikTok: checks 3, 6 and 9 do not apply; post a short video and a 2-photo post.
X also: check that the account's spend rises after a post and a sync, and that a $0.10 budget blocks the next post.
YouTube also: upload a short MP4 (check it appears, private until the audit), reply to a comment.
Instagram also: carousel (2–10 files), reel, private reply within 24 hours
after "Confirm reply agreement". LinkedIn also: company Page (Page ID) and
personal profile.

## Results

| Platform | Date | Checked by | Result | Notes |
|---|---|---|---|---|
| Instagram | | | Not run | |
| LinkedIn (Page) | | | Not run | |
| LinkedIn (profile) | | | Not run | |
| Facebook Page | | | Not run | |
| Threads | | | Not run | |
| YouTube | | | Not run | |
| Pinterest | | | Not run | |
| TikTok | | | Not run | |
| X | | | Not run | |
