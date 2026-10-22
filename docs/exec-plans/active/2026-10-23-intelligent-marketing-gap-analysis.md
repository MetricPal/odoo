# Intelligent Marketing — vision, scenarios and gap analysis

Status: analysis only, nothing implemented. Written 2026-10-23 from the
product owner's brief. Use this as the starting point for an exec plan.

## 1. The brief (owner's words, condensed)

A marketing system that can **research, plan, analyse gaps and risks, propose
solutions and execute them**:

- Recurring (weekly, adjustable) **market research and competitor analysis**.
  Competitors and sources of truth are **approved by the user**, at least the
  first time.
- From the findings, **propose a few campaign options** to run: social,
  messaging, email, SMS, events (virtual or physical).
- **Manage all collected data** for CRM, AI agents and future marketing; feed
  other modules ("one big system").
- **AI assistant** for any analysis, with **reports** in a proper format:
  customisable, readable HTML preview that exports easily to PDF / PPT /
  Excel / Word (a **report generator module**).

Non-negotiables from `AGENTS.md` apply: humans supervise, machines work; any
send/publish/spend is human-approved or runs under an explicitly approved
policy; AI, deterministic workflows, analytics and execution stay separate.

## 2. Target capability map

The loop the system must close, with the layer that owns each step:

| # | Step | Owner (proposed) |
|---|------|------------------|
| 1 | Define the business: products, segments, goals, budget, brand voice | `marketing_intel` (Brand & goals) |
| 2 | Approve sources and competitors | `marketing_intel` + Approval Center |
| 3 | Collect: web pages, feeds, social profiles, reviews, ads libraries, search trends, own data (CRM, sales, web, campaigns) | collectors (connectors) + data hub |
| 4 | Store evidence with provenance (URL, time, hash, licence) | data hub |
| 5 | Analyse: competitor moves, pricing, share of voice, sentiment, trends, SWOT, gaps, risks | AI Agent (skills) + analytics |
| 6 | Recommend: 2–4 campaign options with audience, channel mix, budget, timing, expected result, risks | AI Agent → `marketing_intel` Recommendations |
| 7 | Decide: user picks / edits an option; approval | Approval Center |
| 8 | Execute: create drafts in Social, Messaging, Email, SMS, Events, Website; schedule | orchestrator → existing apps |
| 9 | Measure: UTM, clicks, leads, revenue, cost, attribution | utm / link_tracker / CRM / Sales |
| 10 | Learn: compare result vs prediction; feed next week's research | `marketing_intel` + AI memory |
| 11 | Report: any of the above as HTML → PDF / PPTX / XLSX / DOCX | `report_studio` |

## 3. What exists today (as of 2026-10-23)

| Area | Have | Notes |
|------|------|-------|
| AI runtime | `ai_agent` (Hermes control panel): agents, skills, sources (PDF/text), data scopes, chat, run evidence, usage | **Tool-free, memory-free, no web, no schedules**; one inference per explicit request; no structured output contract |
| AI in apps | `social_ai` (draft posts), `omni_ai` (draft replies), `workflow_ai`, `approval_explain` | Drafting only, always human-reviewed |
| Governance | `approval_center` (frozen evidence, assigned approvers), audit | Strong; reusable for every step that sends, spends or publishes |
| Automation | `workflow_center` (triggers, schedules, branches, approvals, templates) | Can host the weekly cadence; no AI or HTTP-research step types yet |
| Social | `omni_social` (Social Marketing): 8 platforms, composer, preview, campaigns, inbox, `social_utm` | Publishing; **no reading of competitors' public posts, no ads, no listening** |
| Messaging | `messaging_marketing`: audience, opt-in evidence, mailings, approval, STOP | Telegram sandbox only; WhatsApp outbound missing (templates) |
| Email / SMS | Odoo `mass_mailing`, `mass_mailing_sms` (Community) | Available; not yet connected to approvals or AI |
| Events | `event`, `website_event`, `event_sms`, `marketing_card` | Available; no AI planning |
| CRM / Sales / UTM | `crm`, `sale`, `utm`, `link_tracker`, `website` | Attribution basics exist (UTM on leads/orders) |
| Reporting | Odoo views, pivot/graph, `spreadsheet_dashboard` (Community) | **No document/report generator, no PPT/DOCX export** |
| Data hub | Scattered: contacts, mm.contact, omni identities, social inbox | **No unified customer/market data model, no provenance store** |

## 4. Gap analysis

Severity: **H** blocks the vision, **M** limits it, **L** polish.

### 4.1 Research and intelligence

| Gap | Sev | Why it matters | Suggested answer |
|-----|-----|----------------|------------------|
| No source / competitor registry with approval | H | Owner requires approved sources of truth | `mi.source`, `mi.competitor` with approval (first time, and on scope change), allow-list of domains, robots/ToS flag |
| No collectors (web, RSS, sitemap, social public pages, reviews, app stores, ads libraries, Google Trends, news) | H | Nothing to analyse | Pluggable collectors like Omnichannel adapters; fixed hosts, timeouts, rate limits, no login scraping |
| No evidence store with provenance | H | Findings must be traceable and auditable | `mi.snapshot` (url, fetched_at, hash, text, licence, collector), retention policy, dedupe, change detection (diff vs last week) |
| AI agent cannot use tools or the web; no schedules | H | "Recurring research" needs scheduled, tool-using runs | Either (a) Odoo collects and passes bounded evidence to a tool-free run (safer, fits current design), or (b) a separate research Hermes profile with a read-only web toolset. Recommend (a) first |
| No structured AI output (JSON schema) | H | Recommendations must become records, not prose | Skill output contract + validator; reject/retry invalid output |
| Own-data analytics (funnel, cohorts, campaign ROI) | M | Gap analysis needs facts about us, not only competitors | Read models over CRM/sales/utm; KPI snapshots weekly |
| Market sizing / pricing intelligence | M | Strategy quality | Price-tracking collector for approved competitor product pages |
| Social listening (mentions, sentiment) | M | Real-world signal | Extend `omni_social` inbound + public search where APIs allow |
| Search/SEO insight (keywords, rankings) | L | Content strategy | Google Search Console connector (own site only) |

### 4.2 Strategy, risk and recommendations

| Gap | Sev | Suggested answer |
|-----|-----|------------------|
| No brand/goals/budget model (ICP, segments, value props, tone, constraints) | H | `mi.brand` profile, `mi.goal` (target metric, period), budget envelope per channel |
| No recommendation object | H | `mi.recommendation`: problem/opportunity, evidence links, options (2–4), channel mix, audience, budget, timeline, KPIs, predicted result, confidence, risks, compliance notes |
| No risk register | H | `mi.risk`: likelihood × impact, owner, mitigation; auto-flags (consent gaps, budget overrun, brand-safety words, legal claims, competitor-name usage, platform policy) |
| No SWOT / gap templates | M | AI skills producing structured SWOT, positioning map, content gaps, channel gaps |
| No experiment design | M | A/B variants, holdout groups, sample size hint |
| No calendar / conflict view | M | Marketing calendar across Social, Messaging, Email, SMS, Events; detects clashes and fatigue (same person contacted too often) |

### 4.3 Execution (the "and execute them" part)

| Gap | Sev | Suggested answer |
|-----|-----|------------------|
| No orchestrator that turns an approved option into drafts in each app | H | `mi.campaign.plan` → creates Social campaign, Messaging mailing, Email mailing, SMS, Event, landing page draft, all linked to one `utm.campaign`; each child still follows its own approval |
| Email/SMS not under Approval Center | M | Bridge `mass_mailing` to Approval Center like Messaging (freeze body + audience) |
| WhatsApp outbound templates; Telegram beyond sandbox | M | Separate explicit decision (ADR 0011) |
| Paid ads (Meta, Google, TikTok, LinkedIn) | M | Ads connectors with budget caps and approval per spend change; read-only reporting first |
| Events: virtual (Zoom/Meet/Teams/YouTube Live) and physical logistics | M | Event templates + meeting connectors; checklists via Tasks/Project |
| Autopilot policy | M | Pre-approved policies ("boost a post that beats CTR X by ≤ RM 50/day") executed only within limits, logged, revocable — never implicit |
| Fatigue / frequency caps and quiet hours | M | Contact-level caps across all channels in the data hub |

### 4.4 Data hub ("one big system")

| Gap | Sev | Suggested answer |
|-----|-----|------------------|
| No unified person/organisation profile across res.partner, mm.contact, omni.identity, social authors, event attendees, leads | H | Identity resolution layer (deterministic first: phone/email/handle; reviewed merges), consent per channel in one place |
| Consent split (mm.consent, omni.consent, mailing blacklist, SMS blacklist) | H | One consent ledger with channel + purpose; existing models read from it |
| No market/competitor data model | H | Competitor, product, price point, campaign seen, review, mention |
| No event stream for engagement | M | Normalised touchpoints (sent, delivered, opened, clicked, replied, attended, bought) for attribution and AI features |
| Data quality & retention | M | Dedupe, validity, PDPA/GDPR retention and export/erase per person |
| Feeding other modules | M | Stable read APIs / views for CRM scoring, AI sources, sales forecasting |

### 4.5 Reporting ("report generator module")

| Gap | Sev | Suggested answer |
|-----|-----|------------------|
| No report builder | H | `report_studio`: report = template + data blocks (KPI tiles, tables, charts, AI narrative, evidence list); HTML preview editable in-app |
| No multi-format export | H | HTML → PDF (Odoo's wkhtmltopdf/paper muncher already present), XLSX (xlsxwriter present), PPTX (python-pptx), DOCX (python-docx); one block model rendered by each exporter |
| No scheduling/distribution | M | Scheduled reports (weekly marketing brief) via Workflows, delivered by email/Discuss, with approval if external |
| No branding | L | Brand kit (logo, colours, fonts) shared with AI Agent "Brand kit" design |
| Governance of AI-written text | M | Every AI paragraph shows its sources; numbers come from queries, never from the model |

### 4.6 Cross-cutting

| Gap | Sev | Notes |
|-----|-----|-------|
| Cost control for AI and ads | H | Budgets per run/week/company; usage already tracked in `ai_agent` |
| Legal/compliance (PDPA Malaysia, GDPR, CAN-SPAM, platform ToS, comparative-advertising rules, scraping law) | H | Source approval records the legal basis; claims checker before publish |
| Evaluation of AI quality | M | Golden datasets, recommendation hit-rate vs outcomes |
| Multi-company / multi-brand | M | Every record company + brand scoped |
| Explainability for approvers | M | Approval view shows evidence, prediction, risks, cost |

## 5. More real-world scenarios (beyond the example)

1. **Weekly market brief** (the owner's example): collect → diff vs last week
   → AI brief (what changed, why it matters) → 2–4 campaign options → approve
   one → drafts created in each channel → results feed next brief.
2. **Competitor price drop alert**: tracked product page price falls >10% →
   risk card + options (match, bundle, value message) within hours, not weekly.
3. **Competitor launch / campaign detected** (new landing page, ads library
   entry, press release) → counter-positioning content drafts.
4. **Seasonal calendar** (Ramadan, Hari Raya, CNY, Deepavali, 11.11, 12.12,
   school holidays, payday): plan 4–6 weeks ahead with budget split.
5. **Lead nurture gap**: CRM shows leads stalling at a stage → segment + drip
   (email → messaging → sales call task).
6. **Churn / win-back**: customers with no purchase in N days → offer test with
   holdout group.
7. **Event funnel**: webinar or store event → invitations (email/SMS/messaging)
   → reminders → attendance → follow-up offers → ROI report.
8. **Reputation response**: spike of negative reviews/mentions → risk,
   suggested replies (human-approved), internal escalation.
9. **Content gap**: competitors rank/post on topics we don't → content
   calendar suggestions (blog, social, video).
10. **Budget reallocation**: channel ROI below target → move budget proposal
    (approval required for any spend change).
11. **Product launch playbook**: from a product record → positioning, launch
    calendar across all channels, sales enablement one-pager.
12. **Partner / influencer discovery** (approved sources only) → outreach
    drafts, never auto-sent.
13. **Post-campaign review**: predicted vs actual, learnings stored for the AI
    (as reviewed notes, not raw model memory).
14. **Board / management report**: monthly marketing performance as PPTX + XLSX
    appendix from the same report definition.

## 6. Proposed modules

| Module | Purpose | Depends on |
|--------|---------|------------|
| `marketing_intel` | Brand & goals, approved sources/competitors, research runs, findings, SWOT, recommendations, risks, campaign plans, marketing calendar | ai_agent, approval_center, workflow_center, utm |
| `marketing_collect_*` | Collectors (web page, RSS, sitemap, reviews, social public, trends, ads libraries) as adapters | marketing_intel |
| `marketing_data` (data hub) | Unified profiles, consent ledger, touchpoints, identity resolution, retention | contacts, crm, messaging_marketing, omni_* |
| `report_studio` | Report templates/blocks, HTML editor preview, exports PDF/XLSX/PPTX/DOCX, scheduled delivery | web, ai_agent (narratives) |
| bridges | `mass_mailing_approval`, `event_marketing_intel`, ads connectors | respective apps |

## 7. Suggested phases

1. **Foundations** — `report_studio` MVP (HTML + PDF + XLSX, then PPTX/DOCX);
   `marketing_intel` brand/goals, source & competitor registry with approval,
   web-page/RSS collectors, evidence store with change detection.
2. **Weekly brief** — Workflows schedule → collect → AI brief with structured
   output → findings, SWOT, risks → report. Human reads; no execution yet.
3. **Recommendations → drafts** — options with budget/KPIs; approve one →
   orchestrator creates linked drafts in Social, Messaging, Email, SMS, Events.
4. **Measure & learn** — attribution, predicted vs actual, learning notes,
   fatigue caps; data hub v1 (consent ledger, touchpoints).
5. **Scale** — ads connectors (read-only → capped spend), social listening,
   price tracking, WhatsApp templates, autopilot policies within limits.

## 8. Decisions needed from the owner

1. Research engine: Odoo-side collectors feeding a tool-free AI (recommended),
   or a separate Hermes research profile with read-only web tools?
2. Which sources first (own site/CRM, competitor sites, social, reviews,
   Google Trends, ads libraries)? Any paid data providers?
3. Execution scope for v1: drafts only (recommended), or also scheduling?
4. Report formats priority (PDF/XLSX first, PPTX/DOCX next?) and branding.
5. Budget limits for AI usage and, later, ads.
6. Jurisdictions to comply with (Malaysia PDPA by default; others?).
7. Data hub: merge into `res.partner` or keep a separate profile model?

## 9. Risks of the programme itself

- Scraping/ToS/legal exposure → approved sources, robots.txt, no logins, APIs
  where offered.
- AI hallucinated numbers in reports → numbers only from queries; AI writes
  narrative with citations.
- Over-automation → every send/spend through Approval Center or an explicit,
  capped policy.
- Data sprawl / privacy → one consent ledger, retention, export/erase.
- Cost → per-run and weekly AI/ads budgets with hard stops.
