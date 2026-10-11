# Omnichannel LinkedIn

Connect company Pages or personal profiles to **Social** for approved public text, photo and multi-image posts/replies and permitted incoming activity.

Use an existing member access token. [Create a LinkedIn app](https://www.linkedin.com/developers/apps).
`openid`/`profile` identify the token's member. Personal publishing requires
`w_member_social`; personal activity reads require restricted `r_member_social`
and applicable social-feed permissions. Company Pages require a current authorized
Page role and applicable organization read/write, administration and feed scopes.
Community Management is a vetted product; the app's granted permissions determine
available data. A connected profile is not a claim that every permission is granted.

Choose **Company Page** and enter its numeric Page ID, or **Personal profile** to
derive the actor automatically. Versioned REST headers use `202609` and Restli
`2.0.0`. The API client rechecks the member and Page role before publishing and
checks the root post belongs to that exact account before replying.

Private LinkedIn messages are not offered through this connector. Reads use the
API, not scraping. See [Social scope and security](../omni_social/README.md).
Live app access and publication still need verification with an authorized account.

Carousel in the form means organic MultiImage (2–20 JPEG photos), not sponsored
Carousel ads. Images upload from the approved files; ownership and processing
status must be readable with the token’s granted permissions. A write-only member
token may not permit image status reads. Webhooks support approved company Page
notifications: register the callback in the developer portal, then create a Page
event subscription. Personal webhooks and Instagram-style stories/reels are not
supported. See Social README for configuration and media limits.
