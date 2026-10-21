# Project Changelog

Record major architectural, product and implementation changes here.

Format:
- date
- change
- reason
- affected areas
- migration/compatibility notes

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
