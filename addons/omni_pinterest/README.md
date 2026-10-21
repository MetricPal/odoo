# Omnichannel Pinterest

Adds a Pinterest account and board to the **Social** app.

- **Connect**: enter the board to pin to (its name or ID), then sign in with
  Pinterest (developer app ID and secret, redirect URL shown on the account) or
  paste an access token with `boards:read`, `pins:read` and `pins:write`.
- **Outgoing**, each after approval: an image Pin (one image, or 2–5 images
  with the Carousel format). The post's **Subject** is the Pin title (up to 100
  characters), its text the description (up to 500); the first `https://` link
  in the text becomes the Pin's destination link.
- **Incoming**: the board's latest 25 Pins. Pinterest has no comments or
  messages API, so there is nothing to answer.
- **Access tiers**: on Trial access, Pins are visible only to their creator.
  Request Standard access in the Pinterest developer portal (a short demo
  video of the sign-in is required). Apps registered from 14 Sep 2026 may be
  refused boards of non-business accounts.

Live checks: `omni_social/LIVE_CHECKS.md`.
