# Omnichannel Facebook Pages

Adds Facebook Pages to the **Social** app.

- **Incoming**: the Page's latest 20 posts with reactions and comment counts,
  and up to 50 comments per post (the Page's own replies are skipped).
- **Outgoing**, each after approval: text posts, one photo, 2–10 photos in one
  post, one video, and public replies to the Page's posts and comments.
- **Connect**: sign in with Facebook (developer app ID and secret, redirect URL
  shown on the account) or paste a Page access token. A user token is refused.
  If you manage several Pages, enter the Page ID before signing in.
- **Webhooks**: Page `feed` events are signed like Instagram's; enter the app secret,
  register the shown callback URL and verify token, and new comments arrive
  within a minute.
- Photos and videos are fetched by Facebook from the account's public HTTPS
  address while the approved post is publishing.

Messenger chats are private conversations and belong to Omnichannel
(`omni_messenger`), not to Social. Live checks: `omni_social/LIVE_CHECKS.md`.
