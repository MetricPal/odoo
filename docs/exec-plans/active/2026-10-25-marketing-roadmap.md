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

### P1 — Portfolio (status: delivered 2026-10-25)
- Portfolio view across brands and clients: budget vs planned vs spent, results (leads, revenue), goals,
  health (on track / at risk / off track) with the reason; totals and comparison; grouped by company or
  client.
- Programmes: group campaigns under one initiative (e.g. "Q4 launch") with roll-up progress and budget.
- Cross-brand timeline: all campaigns on one time axis (weeks/months), clashes highlighted.
- Client record: retainer/monthly fee, contract period, client contact; client-level report.

### P2 — Consent ledger and preference centre (status: delivered 2026-10-25)
- One consent record per person per channel (email, SMS, WhatsApp, Telegram, social DM) with source and
  evidence; existing Messaging consents, mailing-list opt-outs and blacklists kept in sync.
- Every send path (campaign channels, workflows) checks this ledger.
- Preference page per person (secure link): choose channels and topics, opt out of everything.
- Data requests: export or delete a person's marketing data, approved and audited.

### P3 — Work management (status: delivered 2026-10-25)
- Tasks per campaign with owner, due date and status, reusing Odoo Project (a campaign gets its project);
  templates carry their task list.
- Request intake: a request form that becomes a brief and then a campaign.
- Proofing: versions of creatives and copy, side-by-side compare, approve or request changes.
- Capacity: workload per person across campaigns and tasks.

### P4 — Client collaboration (status: delivered 2026-10-25)
- Portal access for a client contact: their brand's campaigns, progress, results and reports; review and
  approve proofs and campaigns as an external approver where policy allows.

### P5 — Customisable control panel (status: delivered 2026-10-25)
- Users add, remove and arrange panel blocks, save views per role (marketer, advisor, manager), and add
  Report Studio boxes.

### P6 — AI Agent chat control (status: delivered 2026-10-25)
- Create, change, pause and report on campaigns and workflows from an AI Agent conversation; always ending
  in the same reviews and approvals.

## Status log
- 2026-10-25: Programmes replaced by a Target quarter field on campaigns (owner decision): dropdown with
  year, filled from the start date and changeable; filters last/this/next quarter; group by quarter. The
  programme model, menu and portfolio section are removed.
- 2026-10-25: P6 delivered as `marketing_intel_assistant`: plain-words instructions → validated proposal →
  Do it (as the user) for create/change/duplicate/send for review/take out of review/cancel campaigns, reports,
  and pause/resume/approval of workflows. Common phrasings parsed without AI; others read by the user's AI
  agent (tool-free, JSON only). Defaults chosen while away: chat lives in Marketing (not inside the AI Agent
  app's generic chat, whose agents stay read-and-draft); "pause" a campaign means taking it out of review —
  released campaigns are paused in each app or cancelled.
- 2026-10-25: P5 delivered in `marketing_intel_plan` (`mi.panel.layout`): blocks shown, ordered and sized per
  person or per role (managers save role views), Report Studio boxes on the panel, extra blocks from other
  modules (team workload, open requests). Defaults chosen while away: role picked automatically (manager /
  advisor if client brands / marketer); only the panel page is customisable, My to-dos stays a fixed list.
- 2026-10-25: P4 delivered as `marketing_intel_portal`: client contacts per brand, /my/marketing pages
  (waiting for you, results, campaigns, proofs, requests), campaign sign-off before the internal review,
  client proof decisions, portal requests. Defaults chosen while away: the client sign-off is an extra step
  before the internal review (not an Approval Center approver), so releasing still needs the internal approval;
  money is never shown in the portal.
- 2026-10-25: P3 delivered as `marketing_intel_work`: campaign tasks in Project (carried by duplicates,
  repeats and templates with relative due dates), request intake → brief → campaign, proofs with versions,
  word-diff compare and approve/request changes (approved text fills the draft; open proofs block the campaign
  review), team workload report, panel to-dos. Defaults chosen while away: requests are filed by marketing
  users for now (clients file them in P4); marketing users get Project user access.
- 2026-10-25: P2 delivered as `marketing_intel_consent`: append-only ledger per person and channel/topic,
  two-way sync with Messaging consents and the email/phone blacklists, workflow check, public preference page
  (channels, topics, unsubscribe all, evidence), data requests (copy / erasure) executed only after approval,
  backfill on install. Defaults chosen while the owner was away: social DMs are a ledger channel (no sending
  app yet); staff opt-ins need written evidence; erasure keeps addresses suppressed.
- 2026-10-25: roadmap agreed; P0 started.
- 2026-10-25: P1 delivered. Spend lines per campaign (entered by hand, owner's choice) with spent / budget
  left; programmes grouping campaigns (roll-up budget, spend, channels, leads, revenue, health); client fee
  and contract on client brands; Portfolio page (month / quarter / year): KPI cards, brands grouped by
  company or client with budget, spend meter, planned, leads, revenue, revenue/spend, campaigns, goals and
  health with reasons; cross-brand timeline (16 weeks, stacked bars, clashes outlined, next runs hatched);
  programme cards. Health rule: off track when spend exceeds budget or half the goals are behind; at risk
  when >90% spent, campaigns plan more than the budget, a goal is behind or a channel needs fixing.
- 2026-10-25: P0 delivered. Templates show only "Use this template" and their saved texts (no status,
  dates, campaign buttons or AI button); saving again updates the campaign's one template ("Update
  template"); "Your action needed" replaces "For you"; My to-dos is the panel's to-do list (campaigns and
  workflows) with an explanation of what it contains. Next: P1 Portfolio.
