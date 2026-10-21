# Omnichannel TikTok

Adds a TikTok account to the **Social** app for publishing.

- **Outgoing**, each after approval: one video (MP4; the post text is the
  caption, up to 2,200 characters) or a photo post with 1–35 images (the
  **Subject** is the title, up to 90 characters; the text is the description).
- **Connect**: sign in with TikTok (app with Login Kit and Content Posting API,
  `video.publish` scope approved; client key and secret; redirect URL shown on
  the account). Tokens last a day and are renewed with the refresh token.
- **Privacy**: the post uses the most public level TikTok offers the account.
  Until the app passes TikTok's audit, that is "only me", and the result note
  says so.
- **Photos** are pulled by TikTok from the account's public address; verify
  that domain in the TikTok developer portal. Videos are uploaded directly.
- **Not available**: TikTok has no API to read or answer comments, and DMs are
  not offered (they need separate Business Messaging approval and are not
  available in the EEA, UK or Switzerland).
- Each step (open the post, upload, wait for processing) is saved; a lost
  upload shows "Check platform" and is never repeated automatically.
