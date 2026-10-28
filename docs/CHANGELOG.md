# Project Changelog

Record major architectural, product and implementation changes here.

Format:
- date
- change
- reason
- affected areas
- migration/compatibility notes




## 2026-10-28 — Marketing: campaign lifecycle and proposal approvals as activities

- Change: campaigns move through Market Research › Planning › Execution › Results › Evaluation (`mi.plan.phase`); status bar, list strip, badges, kanban columns, filters and the portal use these words.
- Change: Proposal type (Paid, Owned, Earned) decides the approvals (`mi.approval.route`: Paid HOD › Finance › CEO, Owned HOD, Earned HOD › CEO; Finance skipped without budget). Each approval is a To-Do activity; done approves and opens the next (`mail.activity._action_done` hook); Refuse / Request changes ask for a comment (`mi.plan.decision`); Finance cannot request changes; the activity cannot be cancelled.
- Change: approvers: HOD from the owner's department manager (hr), Finance / CEO / fallback HOD in Configuration › Proposal approvers (`mi.approver`); approvers need Marketing access.
- Change: the approved proposal is frozen as a numbered version (`mi.plan.snapshot`); Send for review waits for the proposal approval; repeating runs start in Planning; the AI assistant stops after writing while in Market Research.
- Change: form tabs Overview, Market Research, Execution (design and channels), Results, Evaluation; the Approvals and Spend tabs are gone; Tasks and Spend are links under the campaign name; Cancel campaign is in the gear menu.
- Migration: existing campaigns get the stage of their state (brief → Market Research, content/review → Planning, scheduled/live → Execution, done → Results).

## 2026-10-26 — Marketing: links and buttons only for who may fix it

- Change: the link to the approval type is shown only to approvals managers, the link to the brand's Channels & accounts only to marketing managers; everyone else reads whom to ask instead ("Nobody else can approve it: ask Ali, Siti to add another approver or allow self-approval").
- Change: the same for the error buttons (Set the approvers, Open the brand): someone without the rights gets a plain message naming the managers.
- Change: the owner's next-step activity is worded for the owner (context `mi_step_user`); helpers `can_fix` / `whom_to_ask` in `marketing_intel/models/fixers.py`.
- Fix: the next-step banner is recomputed per user (`depends_context('uid')`).

## 2026-10-26 — Marketing: guidance texts link to the place to fix

- Change: next-step banners on the campaign form (`next_step_html`, `my_todo_html`) link "the approval type “Marketing campaign”" to the approval type and "the brand’s Channels & accounts" to the brand, instead of menu paths like "Approvals › Configuration › …".
- Change: errors that point somewhere raise `RedirectWarning` with a button (Set the approvers, Open the brand, Open the template); the "Not sent for review yet" and AI brief notifications carry links.
- Fix: the assistant and Send for review handle `RedirectWarning` (it is not a `UserError`).

## 2026-10-26 — Marketing: campaign list and form in Odoo's layout

- Change: campaign list with a summary strip (stages with arrows, tiles; js_class `mi_campaign_list`, data from
  `mi.plan.get_campaign_dashboard`), Odoo columns incl. Activities; form with smart buttons (budget, timeline,
  channels, approvals), tabs Overview · Market research · Design · Approvals · Campaign · Execution · Report, gear
  actions Duplicate & edit / Save as template (server actions) and Print › Campaign report (QWeb PDF).
- Reason: owner's proposed campaign page, built with Odoo components (like Sales and Expenses).
- Affected: `marketing_intel_plan` (20.0.1.4.0).
- Migration: upgrade `marketing_intel_plan`; reload the browser.

## 2026-10-25 — Marketing: branching workflows and one menu layout

- Change: workflows get a "Someone submits a form" trigger (website contact form leads or newsletter sign-ups),
  "Send an email" and "Send an SMS" steps (unsubscribes, consent ledger and daily limit respected) and a
  "Split the audience" step (AI decides, words, or lead score) with Path A / Path B steps; an AI split pauses the
  run until the AI answers, then continues on the chosen path (unusable answer → Path B). Steps are edited in a
  popup with a one-line list. New approval type "Marketing workflow" for workflows without WhatsApp/Telegram
  messages (they previously used the campaign approval type, whose model did not match, so they could not be
  approved). New recipe "Form submitted → AI split → email or SMS". Menus: Control panel · Campaigns (All,
  Templates, Goals, Requests, Tasks, Proofs) · Workflows · Insights · Contacts · Configuration (Brands, Consent
  topics, Competitors, Sources, Research history, Assistant history); Work and Assistant top menus removed;
  Templates/Workflows buttons removed from the control panel.
- Reason: owner request (screenshot: form → AI audience split → email / SMS) and fewer menus.
- Affected: `marketing_intel_flow` (now depends on `marketing_intel_ai`, `mass_mailing_sms`), `marketing_intel`,
  `marketing_intel_plan`, `marketing_intel_work`, `marketing_intel_consent`, `marketing_intel_assistant`.
- Migration: upgrade those modules; set approvers on "Marketing workflow".

## 2026-10-25 — Marketing: Odoo activities, fewer menus, New workflow starts from a recipe

- Change: the owner's next step on a campaign (and "ask approval again" / "refused" on workflows, requests to
  answer) is an Odoo activity, done automatically when the step is done; "Your action needed" lists my activities
  on marketing records (approvals open the campaign) plus campaign tasks due this week. Removed the My to-dos
  page and menu, the Portfolio menu (button on the control panel instead) and the Reporting menu (Campaign results
  = Campaigns pivot; Goals moved under Campaigns). Workflows: New opens the recipes, with "Start from scratch".
- Reason: owner feedback: use Odoo Activities, fewer menus and one way to each thing.
- Affected: `marketing_intel` (menu), `marketing_intel_plan` (activities, panel, menus; 20.0.1.3.0 migration
  creates activities for running campaigns), `marketing_intel_flow`, `marketing_intel_work`,
  `marketing_intel_portal`, `marketing_intel_ai`.
- Migration: upgrade those modules.

## 2026-10-25 — Marketing: manage workflow recipes

- Change: recipes get step lines (`mi.flow.recipe.step`, replacing the JSON `steps`), a list and form for
  marketing managers (edit, reorder, archive), "Save as recipe" on workflows (managers; saving again updates),
  "Workflows made from it", and "Use this recipe" asks which brand when there are several (or uses the brand in
  view). Shipped recipes are now `noupdate`, so managers' edits survive upgrades.
- Reason: owner request: recipes could not be managed and could land on the wrong brand.
- Affected: `marketing_intel_flow`.
- Migration: upgrade `marketing_intel_flow`; shipped recipes get their step lines.

## 2026-10-25 — Marketing: Target quarter replaces Programmes

- Change: campaigns get a Target quarter (e.g. 2026 Q4) filled in from the start date and changeable, with
  Last / This / Next quarter filters and a Target quarter group-by. Programmes (model `mi.program`, menu,
  portfolio cards, `mi.plan.program_id`) are removed.
- Reason: owner decision: a quarter field in filters and group-by is simpler than a separate programme record.
- Affected: `marketing_intel_plan`.
- Migration: upgrade `marketing_intel_plan`; existing campaigns get the quarter of their start date. Programme
  records are dropped from the app (the old table stays in the database until cleaned up).

## 2026-10-25 — Marketing: one template per campaign family; template list

- Change: a campaign started from a template, and copies of a campaign, update the family's template instead of
  creating another; a new template cannot reuse the name of another template of the same brand. Templates get
  their own list (template, brand, channels, repeats, budget, saved from, used, owner, last updated) instead of
  the campaign columns (start, channels sent, next step, status).
- Reason: owner found two identical templates from one campaign and its started copy.
- Affected: `marketing_intel_plan`.
- Migration: upgrade `marketing_intel_plan`; archive any duplicate templates created before.

## 2026-10-25 — Marketing: search views on every marketing list

- Change: standard Odoo search views (filters, group-bys, date filters) for goals, competitors, sources,
  research runs, programmes, workflows, workflow runs, recipes, consent history, topics, data requests and
  assistant history; they previously fell back to the empty default search panel.
- Reason: owner feedback: reuse Odoo's own search bar on every list.
- Affected: `marketing_intel`, `marketing_intel_plan`, `marketing_intel_flow`, `marketing_intel_consent`,
  `marketing_intel_assistant` (views only).
- Migration: upgrade those modules.

## 2026-10-25 — Marketing P6: assistant chat

- Change: new module `marketing_intel_assistant`: instructions in plain words become a proposed action
  (create/change/duplicate/review/cancel campaigns, reports, pause/resume/approve workflows) that the user
  confirms; it runs with the user's rights and campaigns/workflows keep their reviews. The control panel gets
  an "Ask the assistant" button.
- Reason: roadmap P6.
- Affected: new `marketing_intel_assistant`; `marketing_intel_plan` (panel button).
- Migration: install `marketing_intel_assistant` (auto-installs); an active AI agent is optional (simple
  instructions work without it).

## 2026-10-25 — Marketing P5: customisable control panel

- Change: the control panel is made of blocks that each person arranges (order, width, add/remove) and saves as
  their view; marketing managers save views per role; Report Studio boxes can be added. Work management adds
  "Team workload" and "Open requests" blocks.
- Reason: roadmap P5.
- Affected: `marketing_intel_plan` (new `mi.panel.layout`, `res.users.mi_panel_view`, panel UI),
  `marketing_intel_work` (panel blocks).
- Migration: upgrade `marketing_intel_plan` and `marketing_intel_work`; reload the browser.

## 2026-10-25 — Marketing P4: client portal

- Change: new module `marketing_intel_portal`: client contacts per brand see campaigns, results, proofs and
  requests in the portal, sign off campaigns before the internal review and decide on proofs.
  `marketing_intel_plan`: the "Your action needed" search accepts the `in` form of the domain.
- Reason: roadmap P4 (agencies working with client brands).
- Affected: new `marketing_intel_portal`; `marketing_intel_plan` (needs_me search).
- Migration: install `marketing_intel_portal` (auto-installs); add client contacts on client brands.

## 2026-10-25 — Marketing P3: work management

- Change: new module `marketing_intel_work`: campaign tasks (Project), requests, proofs with versions and
  compare, team workload, panel to-dos; campaigns are not sent for review while a proof is open.
- Reason: roadmap P3 (Wrike-style work management for marketing teams and agencies).
- Affected: new `marketing_intel_work`; marketing users now imply Project user.
- Migration: install `marketing_intel_work` (auto-installs with Project).

## 2026-10-25 — Marketing P2: consent ledger and preference page

- Change: new module `marketing_intel_consent` (ledger, two-way sync with Messaging consents and blacklists,
  preference page, approved data requests); workflows check the ledger.
- Reason: roadmap P2 (Ketch-style permissioning before more automation).
- Affected: new `marketing_intel_consent`; `marketing_intel_flow` (ledger check).
- Migration: install `marketing_intel_consent` (auto-installs); set approvers on "Marketing data request".

## 2026-10-25 — Marketing P1: portfolio, programmes, spend

- Change: spend entered by hand on campaigns; programmes; client monthly fee and contract on brands;
  Portfolio page (period selector, brand health with reasons, totals by company/client, cross-brand
  timeline with clashes and next runs, programme cards).
- Reason: roadmap P1 (Wrike-style portfolio management).
- Affected: `marketing_intel` (client terms), `marketing_intel_plan` (`mi.plan.spend`, `mi.program`,
  portfolio data and page).
- Migration: upgrade `marketing_intel,marketing_intel_plan`.

## 2026-10-25 — Marketing roadmap and P0 fixes

- Change: roadmap saved (`docs/exec-plans/active/2026-10-25-marketing-roadmap.md`: P0 fixes, P1 portfolio,
  P2 consent ledger, P3 work management, P4 client portal, P5 custom panel, P6 AI chat). P0: templates are
  clean (only "Use this template" and saved texts), one template per campaign ("Update template"),
  "Your action needed" label, My to-dos shows campaigns and workflows that need the user, with an
  explanation.
- Reason: owner review of templates and labels; benchmarks Ketch, Wrike, DirectLync.
- Affected: `marketing_intel_plan`, `marketing_intel_ai` (views).

## 2026-10-25 — Marketing control panel, templates and repeats, workflows

- Change:
  - *Marketing* opens on a **control panel**: KPI cards with 8-week trends, timeline (upcoming/recent,
    recurring marked), campaign progress bars per channel, workflows today, For you, alerts, brand filter.
  - **Reuse**: Duplicate & edit, Save as template / Use this template, Repeat weekly or monthly (new copy
    three days ahead, sent for the quick review).
  - New module **`marketing_intel_flow`**: "when → then" workflows (comment/keyword, private message, event
    registration, email click, lead → WhatsApp/Telegram message, add to list, lead, to-do), approved once then
    automatic, opted-in contacts only, daily limit, run log, 4 recipes.
  - Icons use Odoo 20 Material Symbols.
- Reason: owner asked for a war-room home, reusable campaigns, recurring schedules and workflows such as
  "DM on WhatsApp those who engage with an Instagram post" (likes are not exposed by the platforms; comment
  keyword is the supported equivalent).
- Affected: `marketing_intel_plan` (panel, reuse, repeat cron), `marketing_intel_ai` (fill via shared
  helper), new `marketing_intel_flow` (depends on `messaging_marketing`, `omni_social`).
- Migration: upgrade `marketing_intel_plan,marketing_intel_ai`; install `marketing_intel_flow` (auto-installs
  when its dependencies are present). The Marketing menu now opens the control panel.

## 2026-10-25 — Marketing: clearer statuses, results per channel, My to-dos

- Change: campaign stays in Review until approved (no "Live" from a channel sent outside the review,
  which is flagged); channel statuses Being written / Needs fixing / Waiting for approval / Scheduled /
  Sent / Failed (sent to nobody counts as failed) with a plain Next step per line; Send for review is
  all or nothing with fix instructions; Results tab shows every number each app records per channel;
  "Channels sent 1 / 4" and campaign day replace the bare percentage; "Needs you" became **My to-dos**
  with what to do, and every campaign shows its Next step; the requester is never offered to approve
  their own campaign (and is told when nobody else can).
- Reason: owner feedback on the campaign screen (status unclear, Live while channels were drafts,
  numbers and percentage unclear).
- Affected: `marketing_intel_plan`, `marketing_intel_ai`.

## 2026-10-25 — Marketing: one flow for company marketers and advisors, AI autopilot, one review

- Change:
  - Brands record who owns them (one of our group's companies, or a client); cards are grouped by
    company or client; one brand opens directly.
  - Campaign status line Brief → Content → Review → Scheduled → Live → Done, one status per channel,
    progress bar, history note on every change, **Needs you** menu and brand-card count, automatic
    close after the end date.
  - One review per campaign: new Approval Center type *Marketing campaign* gates Email/SMS/Events;
    Messaging/Social keep their own approvals, decided from the same campaign screen.
  - *Who does the work*: Me or AI assistant. The AI fills the brief, writes every channel (validated
    JSON), sends the campaign for review, and writes the learning note when it is done.
  - Fix: workflow template app label "Marketing" (was "Marketing Intelligence").
- Reason: owner asked for two straightforward ways of working (company marketer, advisor with
  clients, group of companies), AI or human for every channel, less human interaction, visible
  progress.
- Affected: `marketing_intel` (owner type, portfolio), `marketing_intel_plan` (stages, review,
  release, depends on `approval_center`), `marketing_intel_ai` (autopilot, depends on
  `marketing_intel_plan`), `workflow_center` (label).
- Migration: upgrade `marketing_intel,marketing_intel_plan,marketing_intel_ai,workflow_center`.
  Old statuses map Draft→Brief, Ready/Running→Content; brands with a client contact become client
  brands. Set approvers on *Marketing campaign* before the first review.

## 2026-10-25 — Campaign status follows its channels

- Change: a campaign shows Draft (nothing prepared), Ready (drafts waiting in their apps) or Running
  (at least one channel sent, scheduled after approval, or published). "Mark running" removed; Done
  and Cancelled stay manual. The stored status is synced on Prepare, Refresh results and an hourly job.
- Reason: owner saw a campaign marked Running while every channel was still a draft.
- Affected: `marketing_intel_plan` (`mi.plan.status`, `mi.plan.item.live`, cron now hourly).

## 2026-10-25 — Marketing: one brand or many

- Change: Marketing adapts to in-house marketers (one brand: opens the brand) and advisors (several
  brands: brand cards, "My brands" first, grouped by client). Brands get a team, a client contact,
  an email sender and their own channels & accounts; campaign drafts use only those (no fallback to
  another brand's account when the company has several brands). Brand cards flag goals behind
  schedule and budget planned this month.
- Reason: owner described two user types (own company vs marketing advisor).
- Affected: `marketing_intel` (`mi.brand.account`, team fields, home action), `marketing_intel_plan`
  (drafts, brand attention).
- Migration: upgrade `marketing_intel,marketing_intel_plan,marketing_intel_ai`. Companies with several
  brands must set each brand's Channels & accounts before preparing campaigns. Client portal: later.

## 2026-10-25 — Marketing made simple: brands home, campaigns first, plain names

- App renamed **Marketing**; opens on **Brands** (cards with changes, suggestions, active campaigns,
  New campaign / Research now). Menus: Brands · Campaigns · Insights (Market changes, Suggested
  campaigns, Risks) · Reporting (Campaign results, Goals) · Configuration (Competitors, Sources,
  Research history).
- Brand page is the hub: smart buttons and tabs Overview (goals) · Campaigns · Insights ·
  Competitors & sources · Settings · AI assistant.
- `marketing_intel_plan`: campaigns no longer need a suggestion (brand, goal, channels as tags kept in
  sync with the channel lines); **Use this idea** chooses a suggestion and starts its campaign; goals are
  measured by hand or from linked campaigns' results.
- `marketing_intel_ai`: one **✨ Suggest campaigns** button on the brand (uses the latest research,
  researching first if needed).
- Plain names: Campaign (was campaign plan), Suggested campaign (campaign option), Market change
  (finding), Research (research run), Risks (risk register).
- New app icon: AI Agent frame and sparkles with a megaphone (Odoo purple frame, teal megaphone),
  declared in the manifests (`'icon'`) so it shows in Apps; Report Studio icon declared too.
- Module names: Marketing, Marketing: AI assistant, Marketing: campaigns.

## 2026-10-25 — Marketing Intelligence menus

- `marketing_intel`: "Setup" renamed "Configuration"; Research runs moved there
  (below Sources); Findings list shows the Brand, and findings can be searched
  and grouped by brand. Brand form sections renamed "Brand profile" (offering,
  audience, value, voice, markets) and "Budget & research" (was "Plan").

## 2026-10-25 — Reports: side PDF preview, Export in the Board tab, Settings tab

- `report_studio`: the right side of a report shows a PDF preview of the page
  (attachment preview via `mail.thread.main.attachment`, regenerated only when
  the saved content changes, old preview file removed); Export dropdown in
  the Board toolbar (replaces ⋯ › Export); Page and Report options moved to a
  Settings tab.

## 2026-10-24 — Report Studio becomes the Reports page of Dashboards (boxes, grid, page sizes)

- `report_studio` 20.0.2.0.0 (depends on `spreadsheet_dashboard`; own app menu
  removed): **Dashboards › Reports**. Boxes on a 4-column grid (span 1–4):
  title, text, number, chart (SVG, bar/hbar/line/pie/donut), table, list,
  image, hyperlink, view from an app. Visual board editor (add, drag, resize,
  edit dialog with domain editor and field pickers, remove).
- **Add to report** in the ⋯ menu of any list/graph/pivot/kanban (keeps
  filters, grouping, measures); `/report_studio/add_view`.
- Page: A5/A4/A3/Letter/Legal/Tabloid, portrait/landscape, actual/fit/fill;
  per-report PDF paper format.
- **⋯ › Export** submenu (PDF, Excel, PowerPoint, Word, HTML) replaces the
  flat server actions; every format keeps the grid and the page settings
  (native charts in Excel/PowerPoint).
- Fixes: PDF body now uses `web.basic_layout` (UTF-8: "·" no longer "Â·");
  fit script free of template-escaped characters.

## 2026-10-24 — Report Studio: exports moved to the gear menu

- `report_studio` 20.0.1.1.0: PDF, Excel, PowerPoint, Word and HTML exports are
  server actions in the form's gear (⋯) menu ("Export: …") instead of header
  buttons.

## 2026-10-24 — Report Studio: clear message when an export package is missing

- Export buttons check for `xlsxwriter` / `python-pptx` / `python-docx`
  first and explain in a dialog how to install a missing one; the download
  address shows a readable page (400) instead of an internal server error.

## 2026-10-24 — Fix: Report Studio downloads returned an error

- `report_studio`: the download route (`/report_studio/<id>/<format>`) used
  `odoo.http.content_disposition`, which Odoo 20 keeps in
  `odoo.http.stream`; every HTML/PDF/XLSX/PPTX/DOCX download failed with an
  internal server error. Import fixed; HTTP test covers the route.

## 2026-10-24 — Intelligent marketing phase 4a: results and learning

- `marketing_intel_plan` 20.0.1.1.0: results per plan (sent, clicks, leads,
  won deals, revenue, registrations) from mailings, link tracker, CRM, Sales
  and Events by UTM campaign; per-draft sent/clicks; targets vs actual with
  progress; cost per lead and revenue / budget; "What we learned"; daily
  refresh; pivot view.
- `marketing_intel` / `marketing_intel_ai`: brand learning hook; the AI
  analysis now receives past campaigns' targets, results and lessons.

## 2026-10-24 — Intelligent marketing phase 3: campaign plans and drafts

- New `marketing_intel_plan` (auto-installs with Marketing Intelligence):
  campaign plans from chosen options, one UTM campaign, drafts in Social,
  Messaging Marketing, Email, SMS and Events created with the person's own
  permissions (each keeps its own approval), to-dos for channels without an
  app, live draft status, calendar view with overlap warnings.

## 2026-10-24 — Intelligent marketing phase 2: AI brief, options and risks

- `marketing_intel` 20.0.1.1.0: campaign options (`mi.recommendation`, choose /
  reject), risk register (`mi.risk`, likelihood × impact), channels, analysis
  and SWOT on research runs, brief rebuilt with these sections, automatic
  budget and evidence checks, company rules on every record.
- New `marketing_intel_ai` (auto-installs with AI Agent): asks an AI agent for
  a structured analysis per run (manually or after each research run),
  validates the JSON strictly before storing anything, keeps people's work.
- `workflow_center`: built-in template "Market brief review" (12 templates).

## 2026-10-24 — Intelligent marketing phase 1: Report Studio and Marketing Intelligence

- New **report_studio**: block reports (heading, text, KPI, table) over any
  model with the reader's access rights; HTML preview; PDF, Excel, PowerPoint,
  Word and HTML exports. Needs python-pptx / python-docx for PPTX/DOCX.
- New **marketing_intel**: brand and goals; competitors and sources approved by
  an administrator; scheduled collection of public pages and RSS feeds (HTTPS,
  robots.txt, size/time limits); dated evidence with change detection;
  findings; each research run produces a shared brief in Report Studio.
- Plan progress and next steps: docs/exec-plans/active/2026-10-23-intelligent-marketing-gap-analysis.md §10.

## 2026-10-23 — Contacts: Customers filter, social and chat channels

- New module **omni_contacts** (auto-installs with Contacts, Invoicing,
  Employees and Omnichannel): Customers filter below Employees; platform tags
  on the contact list and kanban cards; brand chips and a Social & chat tab on
  the contact form. Chats linked to a contact in Omnichannel appear
  automatically; social profiles are added by hand. Chat identifiers are
  visible only to the chat's Omnichannel team; internal users can read the
  channel catalog (platform names) for the tags.
- **Messaging Marketing** menus: Messaging Marketing, Mailing List, Reporting
  (opens delivery results directly).

## 2026-10-23 — Messaging Marketing: mailings, approval and sending

- **Messaging Marketing 20.0.1.1.0**: mailings. Write one message with
  `{first_name}`/`{name}`, choose lists, and see who can receive it now and
  why others are excluded, a character counter, a chat-style preview and a
  WhatsApp cost estimate. Submitting freezes text, channel and recipients for
  one Approval Center review (the channel's approval type; never self-approved).
  After approval it is queued right away or at the scheduled time; results per
  recipient (sent, not sent with reason, skipped) and link clicks.
- STOP replies on WhatsApp or Telegram record an opt-out automatically.
  **Add to Messaging Marketing** on an Omnichannel conversation creates or
  links the contact (Telegram mailings are sent in that bot conversation).
- **Omnichannel**: `_check_dispatch_authorization` now calls two overridable
  steps, `_approval_targets_command` and `_check_recipient_authorization`
  (default behaviour unchanged), so one mailing review can authorize its
  messages while every other dispatch check still runs (ADR 0011).
- **Telegram**: a 403 for one chat (bot blocked, account deleted) is
  `invalid_recipient`, no longer `unauthorized`; it no longer marks the
  sender unhealthy.
- Limits unchanged and documented: Telegram sends only to its sandbox
  allowlist; WhatsApp cannot send yet.
- Affected: messaging_marketing (new dependencies: approval_center,
  link_tracker), omni_channel, omni_telegram. Upgrade those modules.

## 2026-10-22 — Messaging Marketing: audience and opt-in

- New app **Messaging Marketing** (`messaging_marketing`) for marketing over
  WhatsApp and Telegram, next to Email, SMS and Social Marketing. First stage:
  contacts (normalized WhatsApp numbers, linked Telegram chats), per-channel
  opt-in recorded as immutable evidence, lists scoped to a communication
  team, a blacklist, and adding contacts from Odoo Contacts without opting
  them in.
- Reason: Omnichannel is for conversations; campaigns need audience, consent
  evidence and statistics like the other marketing apps, and must not message
  people who did not agree.
- Affected: new module only (depends on omni_channel, phone_validation, utm).
- Compatibility: install the module; no changes to existing data.

## 2026-10-22 — Social is now "Social Marketing"

- The app (module `omni_social`, menu, Apps list) is named **Social Marketing**,
  alongside Email Marketing and SMS Marketing. Bridge modules follow:
  Social Marketing: AI drafts / Home items / campaign tracking. Home items,
  the Omnichannel hint, scheduled jobs and docs use the new name. Technical
  names (`omni_social`, `social_*`, models) are unchanged.

## 2026-10-22 — Workflow builder: branch lines, step help, preview dialog

- Branches draw a stem from the branch step, a split into Yes and No, and a
  join above the next shared step (paths that end on their own do not join).
  On phones the paths stack and only vertical lines remain.
- Step palette: a one-line explanation under each step and a hover example.
  A click now adds after the selected step or at the end of the main path
  (before: always as the first step when nothing was selected); a hint shows
  where. Drop targets are outlined while dragging. Step settings have a close
  button.
- Preview dialog: "Record" is now **Test on** with an explanation of what to
  pick; **Mode** is a radio choice; Run only when the workflow is active;
  a warning when the document has no record yet; Preview starts without a
  confirmation, Run now keeps one.
- Browser tests updated to the current builder (four were failing before this
  change: missing close button, row clicks, phone breadcrumbs).

## 2026-10-22 — Workflows: own templates, coloured categories, actions from lists

- **Workflows 20.0.1.2.0**: templates are now stored records. Built-in
  templates are refreshed from the code catalogue on install/upgrade and stay
  read-only (archive to hide). **Save as template** on any workflow keeps a
  hidden copy (never activated) that can be edited in the builder; starting
  from it creates an independent draft (its own steps, links and configured
  actions). Templates are managed by Settings administrators.
- Categories (Reminders, Data updates, Create records, Scheduled,
  Integrations, Approvals, Other) have one colour each and a side-panel
  section "What it does"; Applications link to the app module.
- My workflows list and kanban: Preview / run, Activate (only when ready;
  otherwise "Before activation" says why), Pause, Runs, Duplicate, Save as
  template; run and failure counts.
- Migration drops the old `workflow_template` SQL view (pre-migrate).

## 2026-10-22 — Approval Center: archive instead of delete, from the dialog

- Deleting a request that went to review (submitted, approved, refused, or
  cancelled back to "To Submit") now shows the same dialog as a type in use:
  "Not possible to delete … How about archiving it instead?" with an
  **Archive** button. Before, it only said to archive, without a way to do it
  there, and the type could not be deleted either because of those requests.
- Drafts that never went to review can still be deleted.
- The way out: archive the requests, then archive the type. Both leave the
  lists and stay findable with the **Archived** filter; nothing in the audit
  trail is deleted.
- The always-ticked **Active** column of the approval types list is hidden
  by default (archived types are not listed anyway).
- Affected: approval_center (now declares its `web` dependency).

## 2026-10-22 — Social campaign tracking (social_utm)

- New bridge module **social_utm** (auto-installs with Social + Link Tracker).
  Social campaigns get a UTM campaign of the same name (existing campaigns on
  install); posts can choose one.
- Links in a post become tracked short links when it is submitted (campaign,
  platform as source, Social Media as medium, the post as reference), so the
  approver reviews the exact text plus each link's destination. Destinations
  are part of the approved document: a changed tracker blocks publishing.
- Needs a public HTTPS `web.base.url`; otherwise links stay as written and the
  form explains why. Link clicks are shown on posts and campaigns.
- Decision: Social campaigns and UTM campaigns stay separate models and are
  linked; UTM campaigns are a shared label used by CRM, Sales, Email
  Marketing, Website and Recruitment.

## 2026-10-22 — Communication team as radio buttons; Social Media team

- New **Social Media** communication team (omni_channel catalogue). New social
  accounts and campaigns start in it when it exists; it can be changed.
- The communication team is chosen with horizontal radio buttons wherever it
  is edited: Omnichannel channel, channel setup, account, receiving endpoint,
  command and block forms; Social account, account setup and campaign; message
  templates. LinkedIn's account type is a horizontal radio too.
- The platform picker ("Add a social account") shows each platform's mark.
- Campaign "Reason" is now **Note for the approver**, like posts.
- Affected: omni_channel, omni_social, omni_template. Upgrade them; the new
  team is added on upgrade (members still need to be added to it).

## 2026-10-22 — Social: guided post form with live preview

- **Social 20.0.3.0.0**: new post form. Account, action and format are cards
  with illustrations and short explanations, filtered by what the platform
  supports. The text box counts characters against the platform limit. Media
  is a drag-and-drop uploader that lists the limits for the account and
  format, converts PNG/WebP to JPEG in the browser, and shows size,
  dimensions and length. A live preview mimics each platform's layout
  (Instagram, Facebook, LinkedIn, X, Threads, TikTok, YouTube, Pinterest,
  stories/reels, replies).
- "Content" is now **Text**; "Reason" is now **Note for the approver**, with
  placeholders explaining both.
- Connectors declare per-format media rules (`format_media`), a lower photo
  size where needed (`photo_bytes`, X: 5 MB) and a reply length
  (`reply_limit`, Facebook 8,000, YouTube 10,000). Submit enforces them with
  messages naming the platform and format.
- Media records store size, width, height and video length.
- Icons: `fa` classes render nothing in Odoo 20; Social and Approval Center
  views now use Odoo icons.
- Affected: omni_social, the eight social connectors, social_ai (AI brief has
  its own label), approval_center (icons). Upgrade those modules.

## 2026-10-22 — Registry warnings on upgrade

- Upgrading logged "should be searchable" warnings for 14 computed fields on
  channels (setup receiving status and retention days, Telegram overview,
  WhatsApp receiving panel) and on Social accounts (AI summary), plus a
  "Redundant default" on Social posts' company. These fields depended through
  computed links that cannot be searched. They now depend on stored relations
  instead; the retention days are plain computes that write back to the
  receiving rules (one inverse per field).
- No data or behaviour change. A test now fails if any Omni/Social field
  brings the warning back.
- Affected: omni_channel, omni_telegram, omni_whatsapp, omni_social, social_ai.
  Upgrade those modules.

## 2026-10-21 — Social plan, B1 groundwork

Plan: "Social & New Channels Plan" doc (batches B1–B12).

- **Social 20.0.2.2.0**: each connector declares its rules once
  (`providers/capabilities.py`: actions, formats, character and media limits,
  daily caps, prices, sign-in). The post form and submit checks read them and
  name the platform's limit in the error. Account managers can sign in with the
  platform (OAuth: app ID and secret kept in the encrypted vault, one-use hashed
  state, optional PKCE, automatic refresh that keeps pending reviews valid);
  pasting a token still works. A usage meter records each published or
  uncertain action, enforces daily caps and, on paid platforms, a monthly
  budget before the first platform call. Media is served to any platform that
  fetches it from the public address, not only Instagram. Omnichannel's
  channel picker tells people which platforms are connected in Social.
- **Instagram / LinkedIn 20.0.2.1.0**: capability declarations and sign-in.
- Widget check moved from `tools/test_ui.cjs` (removed) to a Hoot suite run by
  `tests/test_ui.py`; new Odoo tests in `tests/test_groundwork.py`.
- Upgrade `omni_social,omni_instagram,omni_linkedin`.
- **B2 guided setup**: Social › Accounts › **Add account** shows platform
  cards (platforms without a connector are dimmed). Connect opens a five-step
  setup (Platform → Connect → Who approves → Receiving → Ready) with plain
  checks at each step; "New approval type" opens a prefilled dialog and picks
  the result. Existing accounts stay as they are (`setup_step = done`);
  unconnected ones show **Continue setup**.
- **B3 planning**: the Social app menus are switched on (earlier versions
  shipped them inactive). Publishing opens as a board (Draft → In review →
  Scheduled → Ready → Published → Needs attention) with calendar and list
  views. Posts can carry a publish time: the time is part of the reviewed
  content, the approval lasts until that time plus two hours (at most 14 days
  after submission), and a cron publishes due posts as their requester; nothing
  publishes early. Campaigns: one text, a version per account, "Submit all"
  and, for reviewers, "Approve all" (each version keeps its own audited
  approval). Decision 2 of the plan taken as proposed.
- **B4 everyday use**: Activity is an inbox (New → Replied / No reply needed,
  Assign to me, "To answer" filter by default; a published reply marks its
  comment Replied; imported posts never count). **Report**: posts published,
  likes, comments and received comments/messages per account and week.
  **Social: AI drafts** (`social_ai`, new, auto-installs with AI Agent) and
  **Social: Home items** (`social_home`, new, auto-installs with AI Home: "N to
  answer on <account>" and posts that need attention). AI Home items may now
  carry a full window action.
- **B5 proof**: all Social checks (protocol, media, webhook, ORM, widget) run
  under Odoo's test runner (`--test-tags /omni_social`, 81 tests); live checks
  with real accounts are listed in `omni_social/LIVE_CHECKS.md` (not run yet:
  they need your test accounts). Omnichannel: the channel setup no longer
  scrolls sideways on phones; the guided-setup UI test follows the
  installed-connector picker.
- **B6 Facebook Pages** (`omni_facebook`, new): Page posts and comments in
  Social; text, photo, multi-photo and video posts and replies after approval;
  sign-in picks the Page token. Messenger follows as `omni_messenger`.
- **B6 Messenger** (`omni_messenger`, new): Facebook Messenger channel type in
  Omnichannel; Page token verification, signed webhook intake of private text,
  approved replies within the 24-hour window checked with Meta. The Meta GET
  webhook handshake moved from `omni_whatsapp` into Omnichannel's inbound
  controller (connectors provide `_<code>_challenge`); remove
  `addons/omni_whatsapp/controllers/` (`git rm -r`).
- **B7 Threads** (`omni_threads`, new): posts and replies with likes and reply
  counts; text, photo, video and carousel posts and replies after approval;
  250 posts / 1,000 replies per day enforced by the usage meter; 60-day tokens
  renewed through the connector's own renewal call (new `oauth_refresh` hook).
  Scheduled posts whose media is still processing now continue automatically.
- **B8 YouTube** (`omni_youtube`, new): uploads with counts and comments;
  approved video uploads (subject = reviewed title) via a two-step resumable
  upload; replies and new comments on own videos; Google sign-in with offline
  refresh. Uploads stay private until the Google project passes YouTube's audit.
- **B9 Discord** (`omni_discord`, new; ADR 0010): Discord bot channel in
  Omnichannel. DMs and chosen server channels arrive through
  `tools/discord_relay.py` (signed, five-minute window); approved replies go
  through Discord's REST API and mention only the person answered. Decision 1
  of the plan taken as the shipped relay.
- **B10 Pinterest** (`omni_pinterest`, new): image Pins (1 or 2–5 images) to
  the board chosen at connect, subject as title, first link as destination;
  board Pins imported. Social: `title_limit` capability makes the subject the
  reviewed title (YouTube now uses it too).
- **B11 TikTok** (`omni_tiktok`, new): approved videos (direct upload) and
  photo posts through the Content Posting API, status followed until
  published; most public privacy level offered (only-me before TikTok's
  audit). No comments API; DMs not built (decision 5 taken as "no").
- **B12 X** (`omni_x`, new): approved posts (up to 4 images) and replies; sync
  of 10 posts and 10 mentions. Every publish (link posts priced higher) and
  every sync is priced and recorded; accounts on paid platforms start with a
  $20 monthly budget (decision 3 taken as proposed) and stop at the cap.

## 2026-10-21

Setup UX review of Approval Center, Workflows and Omnichannel (see the review
document); all nine batches. Upgrade the listed modules and restart.

- **Approval Center 20.0.1.2.0**: cards show "Needs approvers" with a Set up
  button; the approval type form opens on "Who approves" with plain labels and a
  summary; one name ("approval type"), app label "Approvals"; New opens the type
  picker; clearer submit errors; shipped types are `noupdate` and default to the
  requester's manager on new databases.
- **Workflows 20.0.1.1.0**: "Ready to use" templates by default, others dimmed
  under "Needs an app"; settings appear after choosing how to start; department
  workflow managers (ADR 0009) see their departments' workflows and runs and
  can preview, activate and pause those that run as them; depends on `hr`
  (already installed through Approval Center).
- **Workflows: AI drafting (new, auto-installs)** and **Omnichannel: AI reply
  drafts (new, auto-installs)**: drafts proposed by an AI Agent, always reviewed
  by a person. **AI Agent**: runs can notify the record that asked.
- **Omnichannel 20.0.1.24.0**: administrator app launcher; only channel types
  with a connector are offered; "Outgoing messages" and "Receiving rules" names;
  plain retention wording (also Slack, Teams, WhatsApp setup).
- **Telegram 20.0.1.16.0**: the guided wizard stays until setup is complete;
  README describes the in-app bot token as the normal path.

## 2026-10-20

Review and hardening of the custom modules (see the review document). Upgrade
every listed module and restart.

- **Approval Center 20.0.1.1.0**: status, decisions, targets and timestamps change
  only through Submit/Approve/Refuse/Cancel/Execute; submitted content is frozen;
  no self-approval unless the category enables it; sequence and required approvers
  enforced; minimum frozen at submission; audit is append-only and requests with
  history are archived, not deleted; approved actions must be `action_*`/`button_*`
  methods of the category model, run once, and failures are audited. Approvers lose
  create/delete on others' requests; multi-company record rules added. First
  behaviour tests (19). Workflows, Omnichannel and Social extend the new trust hook.
  See ADR 0008. Compatibility: users must cancel a submitted request to edit it.
- **Magic Link Authentication 20.0.1.1.0**: removed the public
  `/auth/magic-link/user-email` lookup (the user switch now keeps each user's own
  email in their browser); same-site redirect check rejects `/\host` forms; exact
  normalized email match (no wildcards); per-address and per-account throttling;
  link emails are queued; the link opens a "Continue" page and only the POST signs
  in; the "check your email" text is set by the server.
- **AI Agent 20.0.1.5.0**: failed status checks retry with backoff instead of
  needing a manager; answers prepared while configuration or access changed are
  discarded; definite 4xx rejections fail instead of "uncertain"; record context
  defaults to recently updated records (configurable per scope); sources share a
  context budget instead of raising; per-user daily limit (default 20); "Ask AI"
  on approval requests prefills an explanation question (nothing is sent until Send).
- **Workflows**: automatic triggers skip records the run-as user cannot read instead
  of failing the editing user's save; manual runs still report the access error;
  webhook request target fixed for URLs with a query and no path.
- **Omnichannel**: one shared credential vault (`OMNI_VAULT_KEY` keeps the key
  outside the data directory, old bundles stay readable); one shared setup-test
  state machine for Slack, Teams and WhatsApp; empty verify tokens rejected for
  social webhooks; Social 20.0.2.1.1 no longer hides approval-category approver
  lines and policy audits (rows with no request) from users; compressed one-line code in the omni addons reformatted (no
  behaviour change, verified by AST comparison).
- **metric.io Branding 20.0.1.2.1**: template overrides are now actually applied,
  when branding installs and whenever an app loads a targeted template later; the
  hard dependencies on Calendar, Events, Recruitment, CRM lead mining and TOTP mail
  were removed (already-installed apps stay installed). An override whose app has
  not loaded yet during an upgrade waits and is applied once all modules are loaded.
- **AI Home 1.2**: My Work history (left), live Needs Your Attention, Automations
  with status filters and Recent (right), composer anchored at the bottom of the
  center; favorites stored per user.
- **AI Home 1.3**: Favorites and the navbar search placeholder removed; the
  composer no longer moves when scrolling (columns scroll on their own); My Work
  fills the screen instead of a "Show more" button; the right column uses readable
  list panels and adds the latest workflow runs.
- **AI Home 1.3 (continued)**: section titles stay fixed while their items scroll;
  the right column shares its height fairly between Automations, Workflow runs and
  Recent with hidden scrollbars; agent picker showing only usable agents; files
  can be attached to a question.
- **AI Agent 20.0.1.6.0**: questions accept up to five attached PDF, text,
  Markdown or CSV files (text extracted in Odoo, files linked to the run); the
  question dialog has a Files field. Sources and attachments share one text
  reader.

## 2026-10-07

- Introduced separate Omni setup-administrator and operator journeys: a five-step
  Start here guide with channel status and scoped navigation, and direct Inbox
  entry for operators. Restricted technical navigation to administrators.
  Added examples and clearer receiving/retention terminology, automatic Telegram
  identity defaults from validated provisioned secrets, and recipient-permission
  navigation from conversations without implicit consent. Versions:
  omni_channel 20.0.1.6.0, omni_telegram 20.0.1.1.0. Upgrade both and restart.
  Validated with 65 passing tests, including Chrome journeys; no live deployment.
  See design decision 0004 for roles, automation boundaries and remaining
  deployment prerequisites.

- Added Recipient Authorization onboarding, clearer field labels, tooltips,
  destination examples, evidence prompts, and expiry/renewal/revocation guidance.
  The form explains that manual identifiers are not verified automatically and
  confirmation sends no message. Added a browser regression covering guidance
  and explicit confirmation. Upgrade `omni_channel` to load the revised view;
  authorization rules and existing records are unchanged by this UI update.
  Validation: module upgrade succeeded on the isolated test database and
  `TestOmniUI.test_recipient_authorization_guidance_and_confirmation` passed in
  Chrome (including the confirmation dialog and no outbound command creation).

- Grouped Omni navigation into Inbox, Messages, Channels, Monitoring and
  Configuration. Replaced generic operator validation with short, specific
  instructions and native buttons opening the exact user or communication team
  in a dialog. Existing access boundaries and actions are preserved. Core
  version 20.0.1.5.1.

- Added system-administrator-managed primary and backup operators to every
  channel's Operations alerts tab, alongside existing alert recipients. Validates
  distinct active internal users against company, communication team and Omni
  access, records assignment audit events, and leaves permissions/automation
  unchanged. Core version 20.0.1.5.0; existing channels start unassigned.

- Added independent PostgreSQL transaction tests for concurrent alert collection
  and rollback after mail insertion/snapshot flush. Verified one durable queue
  entry after contention/retry and no partial persistence on failure. No runtime
  behavior changed; all 13 combined alert checks passed.

- Fixed catalog/channel readiness remaining available after adapter uninstall in
  the same process. Provider registration now identifies its owning addon and UI
  readiness checks the current database's installed modules. Core 20.0.1.4.1;
  Telegram 20.0.1.0.1. Shared factories are retained for other databases.
- Rehearsed native Telegram and core removal on disposable synthetic databases.
  Adapter removal preserves core evidence; core removal deletes Omni tables.
  Documented destructive teardown limits and verified unrelated approval drafts.

- Added loopback SMTP integration tests for native alert/recovery delivery and
  explicit delivery rejection. Validated recipient/MIME content, delivery status
  and no duplicate queueing after failure. No runtime or live mail setup changed.

- Added shared, disabled-by-default operations email policies per channel.
  System administrators explicitly authorize recipients and monitoring; changed
  aggregate counters and recovery use Odoo's existing mail queue. Scope and
  recipient access are rechecked, unchanged states are quiet, native delivery
  failures remain inspectable, and neutralized restores disable alerts.
  Upgrade `omni_channel` to `20.0.1.4.0`; no live policy is enabled by this upgrade.

- Omni-Channel derives webhook URLs from backend `web.base.url`, using
  `channels.[configured hostname]` and the endpoint route key. Removed the draft
  manual server/domain settings and preview. Local-only backends yield no public
  URL. No infrastructure or provider registration changes are executed.
- Existing Odoo outgoing mail remains the transport for future operations
  alerts; the SMTP account does not identify an alert recipient.

## 2026-10-04

- Change: Reworked `approval_center` from an action-first prototype into an
  Approval Types workflow with field rules, seeded default types, dashboard
  request cards, multiple approvers, duplicate-approver protection,
  employee-manager approval, minimum approval defaulting to 1, and hidden
  technical action plumbing.
- Change: Added horizontal Approval Type field-rule controls and an Archived
  filter in the Approval Types configuration list.
- Change: Filtered already-selected approvers out of the approver dropdown on
  Approval Type and Approval Request forms.
- Change: Approval Request forms now materialize Approval Type configuration:
  configured approvers load when the request opens or the category changes, and
  request fields appear only when the type marks them required or optional.
- Fix: Approval Request Period now renders From and To on one aligned row so
  later fields such as Location do not slip into the period block.
- Fix: Approval Request users can now create/update/delete approver lines on
  their own requests, while Approval Type approver configuration remains
  administrator-controlled. Approvers can update their own approver line status.
- Fix: Submitted approval requests now notify approvers through Odoo's
  notification engine in addition to scheduling review activities.
- Fix: Review activities now set a visible Summary so the My Activities list
  shows the approval request prompt instead of an empty summary column.
- Fix: Restored Approval Center review activity completion with
  `activity_feedback()` on approve/refuse/cancel.
- Fix: User deletion with Calendar installed now removes the deleted user's
  `calendar.user` memberships with `sudo()`, because Odoo Calendar's
  `res.users.unlink()` cleanup was failing for users allowed to delete
  `res.users` but not allowed to delete another user's calendar membership.
- Reason: Match the researched Odoo Approvals user model and keep target
  model/action details out of the requester experience.
- Affected areas: `approval_center` models, views, access rules, tests, and Odoo
  verification references.
- Migration/compatibility notes: New module was still in foundation stage.
  Databases that installed the earlier prototype should upgrade before real use.

- Change: Added the `approval_center` module foundation with approval requests,
  policies, audit logs, security groups, backend views, module identity, and a
  custom icon.
- Reason: Start the real Approval Center module using the researched Odoo
  approval model: project policy and audit first, execution through app-specific
  Odoo actions.
- Affected areas: `approval_center`, approval governance docs, Odoo verification
  references.
- Migration/compatibility notes: New module only. Full database-backed install
  validation still requires PostgreSQL availability.

- Change: Updated authentication branding states, shared auth footer, public
  auth `v` query alias, AI Home Favorites star visibility, and AI Home card
  hover/focus styling.
- Reason: Match requested UX for reset-password, magic-link confirmation,
  authentication footer/privacy visibility, and AI Home interaction states.
- Affected areas: `branding`, `auth_magic_link` inherited auth shell,
  `auth_signup` inherited reset-password page, `web` inherited login page, and
  `ai_home` dashboard UI.
- Migration/compatibility notes: Uses Odoo 20 QWeb inheritance and the existing
  standalone auth shell. Full database-backed module validation still requires
  PostgreSQL availability.

## 2026-10-08 — Omni-Channel specification alignment (20.0.1.7.0)

- Replaced permanent setup navigation with scoped Overview/welcome and a separate
  generic six-step Add Channel wizard; successful activation returns to detail.
- Aligned Configuration and Monitoring menus, added Settings Technical placement,
  and moved dispatch internals into expandable Technical Details.
- Added endpoint health verification/status and operational connection/inbound
  summaries. Reused single-sender selection, endpoint ownership, blocklist-first
  intake, audit and approval mechanisms; no new provider integrations or dispatch
  authorization bypasses.
- Added catalog-wide mocked setup, empty-state, activation, multi-endpoint,
  role-scope, navigation and browser coverage. See the specification's
  implementation report for exact validation results and deployment boundaries.

## 2026-10-08 — Omni technical administration (20.0.1.8.0)

- Removed the app launcher, Overview and setup wizard in favor of Settings →
  Technical → Omni-Channel, after Phone / SMS.
- Reduced navigation to Channels, Messages, Policies and Blocklist. Connections
  and diagnostic actions remain accessible from scoped channel records.
- Explicitly replaces legacy menu groups during upgrades to restrict Technical
  navigation to system administrators. Preserves business-facing runtime APIs,
  provider checks, approvals, company/purpose scope and existing records.

## 2026-10-08 — Technical menu ordering

Moved Omni-Channel before Email under Technical as requested (sequence 0).

## 2026-10-08 — Clear settings and delivery monitoring (20.0.1.9.0)

- Replaced cramped form groups with responsive fields whose labels sit above
  inputs; moved explanations next to retention and blocklist settings.
- Added connection selection to blocklist drafts, with server-validated scope
  defaults and compatibility for existing blocks.
- Technical Messages is now a read-only delivery monitor with status filters.
  Existing business composition/approval actions remain separate.
- Channel forms show an explicit warning when a catalog type has no adapter.

## 2026-10-08 — Correct Email adjacency

Corrected the Technical order to Discuss → Activities → Omni-Channel → Email.
The navigation test now asserts immediate adjacency, not merely a lower sequence.

## 2026-10-09 — Workflows

Added the Workflows app with a When → If → Do template catalog, visual
builder, optional Approval Center steps, and persistent run history. Includes
native action configuration, record/date/webhook triggers, schedules, waits,
branching, bounded related-record loops, previews and explicit activation.
Tracked webhook failures require reconciliation for uncertain deliveries.
Templates name missing apps and configuration; AI drafting and provider chat
remain explicitly unavailable until integrated.

Workflows opens from the app menu with its own icon. Upgrades move the existing
menu out of Technical while preserving administrator access.

Moved Overview, Run history and My approvals into Odoo's native app navbar.
Replaced the separate navigation strip and right-aligned New workflow button
with the standard control panel and left-aligned New button.

Removed the My approvals shortcut and its dedicated action from Workflows.
Approvers use Approval Center; Workflows navigation contains Overview and Run history.
