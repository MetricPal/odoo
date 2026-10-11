# Instagram and LinkedIn social workspace

User scope: Instagram private messages plus public social activity; LinkedIn
company Pages **and** personal profiles. Keep concise controls and do not modify
Omnichannel/Telegram source. Existing messaging outbox does not model public
publishing, so `omni_social` owns social review and execution; `omni_instagram`
and `omni_linkedin` supply fixed API clients. No existing connector source changes.

```mermaid
flowchart LR
  Instagram -->|posts/comments/private text| Activity
  LinkedIn -->|permitted posts/comments| Activity
  Activity --> Draft
  Draft -->|exact content/account/destination| ApprovalCenter
  ApprovalCenter --> Approved
  Approved -->|committed claim| Provider
  Provider --> Result
  Result -->|uncertain| ManualCheck[Check platform; no retry]
```

Screens: Activity, Publishing, Accounts. Native Odoo sheet/list controls remain.
An account connection verifies the profile; it does not promise every API
permission. Reads show unavailable capabilities. Personal LinkedIn reads need
restricted access; no LinkedIn DM API is offered.

Initial supported publishing: Instagram single JPEG photos and text replies to
comments/private messages; LinkedIn text posts and text public replies. Engagement
counts accompany imported posts. Latest bounded snapshots are synced on explicit
manager action; this is not a webhook stream or complete historical archive.
Reels, stories, carousels, ads, full analytics, scheduled posting, media replies,
and bulk actions are outside this initial release.

Private Instagram replies need explicit recipient agreement and a verified recent
incoming conversation within the 24-hour window; blocked identities stay blocked.
Every outbound action requires a separate assigned approver and current policy.
Photos are stored immutably in the draft; their hash is frozen in review. Meta can
fetch only a token-addressed JPEG during a live approved publishing claim; the URL
expires with review. This avoids fetching arbitrary media URLs inside Odoo.

Claims commit before network calls. Instagram container creation is one durable
stage; a later explicit Publish resumes that container, checks processing status,
and makes at most one final publish POST. Pending or unknown claims cannot repeat.
A process crash leaves Publishing and requires platform inspection. No automatic
retry, scheduler or public test post is enabled. Rejected actions remain retained;
a new draft needs new review. Approval/configuration/consent changes invalidate
future claims, but cannot recall an already claimed external request.
