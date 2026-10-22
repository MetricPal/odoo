# Social Marketing: campaign tracking

Connects Social to Odoo's UTM campaigns, the ones Link Tracker, CRM, Sales,
Email Marketing and Website report on. Installs automatically when Social and
Link Tracker are both installed.

- **Social campaigns** get a tracking campaign with the same name (or pick an
  existing one). Each version of the campaign uses it.
- **Posts** can choose a tracking campaign; **Track links** is on by default.
- **On Submit for approval**, links in the text become short links
  (`https://<your Odoo>/r/…`) tagged with the campaign, the platform as source
  (Odoo's Facebook, X, LinkedIn, Instagram and YouTube sources; TikTok,
  Threads and Pinterest are created once) and **Social Media** as medium.
  The approver sees the exact text and, under **Link destinations**, where
  each short link leads. If a destination is changed after approval, the post
  cannot be published.
- **Link clicks** on a post or a campaign opens the clicks. Leads,
  opportunities and orders from those visitors carry the same campaign,
  source and medium in CRM and Sales.

Short links only work when Odoo is reachable from the internet: tracking needs
`web.base.url` to be a public HTTPS address. Otherwise links stay as written
and the post form says why. Private replies are never shortened.

Why separate from Social campaigns: the UTM campaign is a shared label used by
many apps; the Social Marketing campaign is a publishing workflow (versions, schedule,
approvals). They are linked, not merged.
