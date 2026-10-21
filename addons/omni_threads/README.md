# Omnichannel Threads

Adds Threads profiles to the **Social** app.

- **Incoming**: the latest 20 posts with likes and reply counts, and their
  replies (your own replies are skipped).
- **Outgoing**, each after approval: text, one photo, one video, carousels of
  2–20 items, and replies under your posts. Text is limited to 500 characters.
- **Limits**: Threads allows 250 posts and 1,000 replies per profile in 24
  hours; the account shows how many were used, and publishing stops at the cap.
- **Connect**: sign in with Threads (Meta developer app with the Threads use
  case; app ID and secret; redirect URL shown on the account) or paste a
  long-lived token. Sign-in tokens last 60 days and are renewed automatically
  before they expire.
- Publishing is two steps on Threads (container, then publish); each step is
  saved, so an interrupted publish continues instead of posting twice. Videos
  wait until Threads has processed them; scheduled posts continue on their own.

Live checks: `omni_social/LIVE_CHECKS.md`.
