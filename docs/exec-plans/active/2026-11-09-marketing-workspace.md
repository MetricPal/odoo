# 2026-11-09 Marketing: the team's whole working day inside metric.io

Status: plan agreed 2026-11-09. M0 done (audit below); M1 and M3 built 2026-11-09 in `marketing_intel_team` from the
approved boards 5.1 to 6.3. Next: M2 writing tools. New screens need approved mocks first (CLAUDE.md); the
role model and assistant jobs are proposed in ADR 0016 (`docs/design-decisions/0016-marketing-roles-and-jobs.md`).
Builds on the marketing roadmap (P0 to P6 delivered 2026-10-25), ADR 0012 (department assistants), ADR 0014
(the assistant as a shared service) and ADR 0015 (agents working together).

## What the owner asked (2026-11-09)

Marketing is one of the primary apps. Marketing people (head of department, seniors, juniors) do their daily work
in the system, without leaving it for ChatGPT (paraphrase, research, analysis) or Canva (posts, carousels,
posters). Each role sees reports and dashboards from its own perspective. The assistant user, workflows and
automations do their share of the work, and people can follow those jobs and their health. Marketing uses every
channel: email, SMS, messaging (WhatsApp/Telegram) and social. Workflows and the assistant do a marketing user's
daily jobs.

## Where it stands (verified in this tree)

| Need | What exists | Gap |
|---|---|---|
| Plan and run campaigns on all channels | `marketing_intel_plan`: campaigns, goals, templates, target quarter, one review (Approval Center), results; channels: Email (`mass_mailing`), SMS (`mass_mailing_sms`), Messaging (`messaging_marketing`), Social (`omni_social`, 8 platforms, carousel format) | WhatsApp outbound templates (Messaging is Telegram-first); one results view across the four channels per campaign is partial |
| Write without ChatGPT | AI drafts: campaign write (`autopilot`), social post and reply drafts (`social_ai`), brief, assistant chat (`marketing_intel_assistant`) | No **writing tools on any text** (rewrite, shorter, longer, tone, translate, fix grammar, hashtags, subject lines) in email, SMS, message and post editors |
| Research without ChatGPT | Brand research runs (`research_agent`, collectors, sources, evidence, findings, risks, suggested campaigns) | No **ad-hoc research** ("what are competitors doing on Instagram this month?") with web search; Hermes's `web` toolset exists but is not used by Marketing |
| Analysis | Report agent (takeaway and evaluation), portfolio, Report Studio boxes | No **"explain this"** on dashboards and reports; no weekly/monthly narrative per role |
| Design without Canva | Social media library (photos, videos), proofs with versions | No **design studio**: brand kit, templates for post / carousel / story / poster / email header, AI images (Hermes `image_gen` toolset exists, unused) |
| Roles | Marketing groups: User, Administrator; panel views Marketer / Advisor / Manager (picked automatically) | No **Head of department / Senior / Junior**: rights, review chain and dashboards per role |
| Assistant and automations do the work | Workflows (customer journeys) in `marketing_intel_flow`; internal workflows with the **Ask agent** step (`workflow_center` + `workflow_ai`); AI Activity, capacity, paused models (ADR 0014) | No **marketing jobs** (recurring work the assistant does: weekly post drafts, comment replies, weekly report…) ready to switch on, and no single **Jobs and health** view for marketing |
| People follow the machines | AI Activity (all agents), workflow run history | Nothing per marketing job: last run, next run, success rate, waiting for whom, failures with the reason |

## Proposal

### 1. Roles: Head of department, Senior, Junior (ADR 0016)

- Three Marketing groups, each implying the one below: **Junior** (does the work), **Senior** (reviews and plans),
  **Head of department** (decides, owns budget and the team). Administrator stays for configuration.
- What changes per role:
  - **Junior**: drafts campaigns, posts, emails and designs; works on assigned tasks; submits for a senior's
    review. Cannot release (send/publish) on their own.
  - **Senior**: everything a junior does, plus reviews juniors' work (accept / request changes), plans
    campaigns, releases within the limits HOD sets (budget, audience size, channels).
  - **Head of department**: everything, plus approves above the limits, budgets, the team's workload and the
    assistant's jobs; sees the whole department.
- The existing one review (Approval Center) gets a **senior review step** for juniors' work before the current
  release approval; above-limit releases go to HOD. The department's head is the HR department's manager, so it
  matches ADR 0012 (the Marketing department's AI assistant).

### 2. A dashboard per role ("My day", "My team", "Department")

Built on the existing control panel (role views already exist), with new blocks:
- **Junior: My day**: my tasks due, my drafts and proofs waiting for changes, what the assistant prepared for me
  (drafts to check), today's scheduled posts and sends, my results this week.
- **Senior: My team**: reviews waiting for me, team tasks late, campaigns at risk, channel performance (email
  open/click, SMS delivery, message replies, social reach/engagement), the assistant's jobs that need a person.
- **HOD: Department**: portfolio (budget vs spend, leads, revenue), results by channel and by campaign, team
  workload and lateness, approvals waiting for me, **assistant and automation health** (jobs succeeding, failing,
  queued; AI usage and cost), month vs last month.
- **Explain this** on every block: the assistant writes a short reading of the numbers for that role.

### 3. Do the daily work inside metric.io

1. **Writing tools** (one button on every marketing text: email body and subject, SMS, message, social post,
   campaign texts): Rewrite, Shorter, Longer, Tone (friendly / formal / bold), Translate, Fix grammar, Hashtags,
   Subject lines (A/B), Fit to channel limit. Each shows a suggestion beside the text with Use / Discard; nothing
   is replaced silently. Runs through `ai.agent.run._ask` (caller Marketing).
2. **Research desk**: ask a research question; the Marketing assistant searches the web (Hermes `web` toolset,
   switched on for the Marketing profile only) and Odoo data; the answer cites sources and can be saved as
   findings or turned into a suggested campaign. Uses the existing sources/evidence/findings models.
3. **Design studio** (instead of Canva), in two steps:
   - **3a. Brand kit and templates**: logos, colours, fonts, and templates per format (square post 1080×1080,
     portrait 1080×1350, story 1080×1920, carousel slides, poster A4/A3, email header). Fill text and pick an image
     (library, upload or **AI image** via Hermes `image_gen`), the assistant suggests copy per slide; export PNG/PDF,
     straight into the social composer's media, an email or a proof. Rendered on the server from HTML templates
     (as Report Studio renders documents), so every design is on-brand.
   - **3b. Free editor**: move, resize and layer elements on a canvas (text, shapes, images), duplicate a design
     for another format. Larger; after 3a is used.
4. **Content calendar** (all channels on one calendar: posts, emails, SMS, messages, with drag to reschedule)
   on top of the existing timeline.

### 4. The assistant and workflows do the jobs; people follow them

- **Marketing jobs**: ready-made recurring jobs, each a `workflow_center` workflow with an Ask agent step run as the
  Marketing assistant user, ending in drafts and review queues, never a send:
  - Junior jobs: draft next week's social posts from the calendar and goals; draft replies to new comments and
    messages; prepare the weekly newsletter draft; tag and summarise new leads from campaigns.
  - Senior jobs: weekly performance summary per channel; flag campaigns at risk with the reason; competitor
    watch (web) every Monday.
  - HOD jobs: monthly department report (Report Studio, PDF); budget burn alert; team workload alert.
- Each job has an **owner** (who receives its output), schedule, and limits (ADR 0014 caller limits).
- **Jobs and health** page in Marketing: every job and customer workflow with status (healthy / failing /
  waiting for a person / paused), last run and result, next run, success rate (30 days), average time, AI usage,
  the reason of the last failure, and Run now / Pause. The owner gets a to-do when a job fails twice. HOD sees all,
  seniors their team's, juniors their own.

### 5. All four channels, one campaign

- Verify and finish: every campaign can carry Email, SMS, Messaging and Social parts, with one review, one
  schedule and one results view per channel (sent, delivered, opened/clicked or read/replied, engagement, leads,
  revenue).
- **WhatsApp outbound templates** in Messaging (approved template messages), so Messaging is not Telegram-only.

## Phases (each: mocks first where there is new UI, tests, browser check, docs, commit on approval)

| Phase | Content | Depends on |
|---|---|---|
| M0 | Audit on the live database: the four channels end to end on one campaign; list what breaks | — |
| M1 | Roles (Junior / Senior / HOD), senior review step, limits per role | ADR 0016 |
| M2 | Writing tools on every marketing text | — |
| M3 | Role dashboards ("My day", "My team", "Department") with Explain this | M1 |
| M4 | Marketing jobs (ready-made) + Jobs and health page | M1, ADR 0014/0015 |
| M5 | Research desk (web) | Marketing profile with the web toolset |
| M6 | Design studio 3a: brand kit, templates, AI images, export to composer/email/proof | image model in Hermes |
| M7 | Content calendar across channels | — |
| M8 | WhatsApp outbound templates; per-channel results on the campaign | M0 findings |
| M9 | Design studio 3b: free editor | M6 used |

## Mocks

M1 and M3, for review: https://claude.ai/artifact/2LVfq6Lxf7YsLnannqCJLn ("Marketing workspace" section):
5.1 Team and roles, 5.2 Campaign senior review and release within limits, 6.1 Junior: My day, 6.2 Senior: My team,
6.3 Head of department: Department (with the setup checklist from M0 and assistant/automation health).

## Owner decisions (2026-11-09)

- Review chain: yes. Junior work goes to a Senior review; Seniors release within limits set by the Head of
  department; above them, HOD approves.
- Design studio: templates and AI images first (3a); the free editor (3b) later.
- Order: M0 audit, then M1 roles and M3 role dashboards, then the rest as listed.
- The Marketing assistant's Hermes profile gets the web search and image generation toolsets (image generation
  needs an image model enabled in Hermes).

## M0 audit: one campaign on all four channels (2026-11-09)

Run on a private copy of the live database (`m0_audit`, never the live one): a campaign with Email, SMS,
Messaging and Social, through prepare, proposal, review and release, as an administrator.

| Step | Result on live data | Why |
|---|---|---|
| Prepare drafts | **Works**: one draft per channel in its app (Email and SMS mailings, a Messaging mailing, a Social campaign) | — |
| Submit the proposal | **Blocked for every campaign**: "Nobody is set as HOD approver for this company." | No HOD approver configured, and campaign owners have no HR department manager |
| Channel accounts | **Blocked**: the brand has no accounts, so every channel asks to "choose" lists, channel and pages | Brand → Channels & accounts is empty (the company has 1 mailing list, 4 messaging channels, 3 social pages, not linked to the brand) |
| Messaging | **Blocked** even with the brand's channels linked: no Messaging list exists | No `mm.list` in the company |
| Social | **Blocked**: "LinkedIn: Connect an active account first." | Social pages exist but are not connected |
| Email and SMS | Reach the review once lists are linked and text is written | — |
| WhatsApp marketing | **Cannot send outside a person's 24-hour window**: Messaging has no WhatsApp template messages | Meta only allows approved templates for marketing; not built |
| Results per channel | Email/SMS: sent, delivered, opened, clicked, replied, failed. Messaging: sent and clicks only (no delivered/read/replied). Social: posts, likes, comments (no reach/impressions) | What each app records today |

What this means for the plan:
- **Setup is the first blocker, not code**: a new marketing team cannot run a campaign without a HOD approver, brand
  accounts, a Messaging list and connected social pages. M1 (roles) fixes the HOD part (department manager or a
  configured HOD, chosen in one place); a **setup checklist** on the Department dashboard (M3) shows what is
  missing with a button to fix each item, instead of failing at submit.
- HOD already exists in the proposal route (`mi.approval.route`, roles HOD / Finance / CEO; HOD = the owner's
  department manager, else the configured HOD). M1 builds Senior and Junior on top of that, not beside it.
- M8 must add WhatsApp templates, Messaging delivered/read/replied, and Social reach from the platforms that give it.

## Not in this plan

Paid ads management (Meta/Google Ads), social listening beyond the web search, video editing.
