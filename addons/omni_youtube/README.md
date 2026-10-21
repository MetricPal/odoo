# Omnichannel YouTube

Adds a YouTube channel to the **Social** app.

- **Incoming**: the latest 20 uploads with like and comment counts, and up to
  50 comments per video (your channel's own comments are skipped).
- **Outgoing**, each after approval: a video upload (one MP4; the post's
  **Subject** is the video title, the text its description) and replies to
  comments or new comments on your videos.
- **Connect**: sign in with Google (Google Cloud project with the YouTube Data
  API enabled, an OAuth client of type "Web application", the redirect URL
  shown on the account). Access lasts an hour and is renewed automatically with
  the refresh token Google returns on sign-in.
- **Audit**: until the Google project passes YouTube's API compliance audit,
  YouTube keeps every API upload private; the result note says so. Uploads also
  count against the project's daily upload quota (shown as 100 a day).
- Upload is two saved steps (open the upload session, send the file). If
  sending the file is interrupted the post shows "Check platform"; it is never
  uploaded twice automatically.

Live checks: `omni_social/LIVE_CHECKS.md`.
