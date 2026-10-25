# Marketing roadmap: execution, management, permissions

Owner, 2026-10-25: "all directions matter". Benchmarks reviewed: Ketch (consent and permission
infrastructure), Wrike for marketing (work management, portfolio, proofing, capacity), DirectLync (SMB
all-in-one, client switching). Today Marketing is strong on execution (channels, one review, AI writing,
workflows, results) and weak on management (portfolio, tasks, timeline, capacity, client collaboration)
and permissions (one consent record across channels).

## How the work is managed

- One phase at a time, in the order below. Each phase ends with: tests passing, a browser check with
  screenshots, docs (README, CHANGELOG, this file), a commit, files copied to the owner's folder and
  verified. The owner pushes.
- This file is the source of truth: each phase gets a status line and a short "delivered" note.
- Decisions that change scope are asked at the start of a phase, not mid-way. Small choices follow
  sensible defaults and are reported.
- Principles kept throughout: reuse Odoo apps first (Project, Approvals, Portal, Website); humans approve
  anything that sends, publishes or deletes; AI drafts, people decide; company and brand access respected.

## Phases

### P0 — Fixes and clear wording (status: delivered 2026-10-25)
- Templates show only template actions (no Cancel / Start again / Refresh / status bar).
- Saving a campaign as a template again updates its existing template instead of duplicating it
  (or makes a new one only when asked).
- "For you" becomes "Your action needed" with the reason; "My to-dos" also lists workflow approvals and
  changed workflows, same as the control panel.

### P1 — Portfolio (status: planned)
- Portfolio view across brands and clients: budget vs planned vs spent, results (leads, revenue), goals,
  health (on track / at risk / off track) with the reason; totals and comparison; grouped by company or
  client.
- Programmes: group campaigns under one initiative (e.g. "Q4 launch") with roll-up progress and budget.
- Cross-brand timeline: all campaigns on one time axis (weeks/months), clashes highlighted.
- Client record: retainer/monthly fee, contract period, client contact; client-level report.

### P2 — Consent ledger and preference centre (status: planned)
- One consent record per person per channel (email, SMS, WhatsApp, Telegram, social DM) with source and
  evidence; existing Messaging consents, mailing-list opt-outs and blacklists kept in sync.
- Every send path (campaign channels, workflows) checks this ledger.
- Preference page per person (secure link): choose channels and topics, opt out of everything.
- Data requests: export or delete a person's marketing data, approved and audited.

### P3 — Work management (status: planned)
- Tasks per campaign with owner, due date and status, reusing Odoo Project (a campaign gets its project);
  templates carry their task list.
- Request intake: a request form that becomes a brief and then a campaign.
- Proofing: versions of creatives and copy, side-by-side compare, approve or request changes.
- Capacity: workload per person across campaigns and tasks.

### P4 — Client collaboration (status: planned; owner earlier: "internal for now, later")
- Portal access for a client contact: their brand's campaigns, progress, results and reports; review and
  approve proofs and campaigns as an external approver where policy allows.

### P5 — Customisable control panel (status: planned)
- Users add, remove and arrange panel blocks, save views per role (marketer, advisor, manager), and add
  Report Studio boxes.

### P6 — AI Agent chat control (status: planned; owner: "later")
- Create, change, pause and report on campaigns and workflows from an AI Agent conversation; always ending
  in the same reviews and approvals.

## Status log
- 2026-10-25: roadmap agreed; P0 started.
- 2026-10-25: P0 delivered. Templates show only "Use this template" and their saved texts (no status,
  dates, campaign buttons or AI button); saving again updates the campaign's one template ("Update
  template"); "Your action needed" replaces "For you"; My to-dos is the panel's to-do list (campaigns and
  workflows) with an explanation of what it contains. Next: P1 Portfolio.
