# UX / Design System Direction

## Design philosophy

The ERP should feel like a business operating system rather than a collection of forms.

Primary interaction:
Review → Understand → Approve/Reject → Done.

## Web

- Odoo-inspired top bar
- Anchored Floating Command Panel for App Launcher
- No permanent left sidebar as the primary application navigation
- AI actions available in context
- Approval Center highly accessible
- AI Workstream as a central work surface

## Odoo view principles

Reuse existing Odoo CSS and DOM structure by default. Add custom styling or
layout wrappers only when the user requests those changes.

The user's five reference screenshots establish the following design boundaries.
Use their structure as guidance, not their sample records, exact dimensions, or
empty-state overlays as requirements.

- **Form (`_form.png`):** manage the record content inside the white sheet (the
  left box on desktop): headings, fields, groups, spacing, and tabs as needed.
  The app bar, control panel, action/status area, and chatter remain native Odoo
  surfaces unless the task explicitly calls for changes there. Preserve native
  responsive behavior rather than fixing the sheet to screenshot dimensions.
- **Cards (`_cards.png`):** manage the design of each card: primary identity,
  supporting details, avatar/image, and relevant indicators or actions. Use the
  native ungrouped kanban grid around the cards.
- **Kanban board (`_kanban_board.png`):** preserve the grouped workflow columns,
  stage headings, and native board interactions; design the record cards within
  that structure. An ungrouped card grid and a stage-based board serve different
  purposes even though both use Odoo kanban views.
- **List (`_list.png`):** choose a concise default set of essential columns.
  Include the remaining relevant business columns in the view as
  `optional="hide"`, so users can enable them through Odoo's column selector.
  Do not silently omit these columns or display every column initially. Keep
  technical helper fields hidden and preserve field/group access restrictions;
  optional visibility does not grant or enforce permission.
- **List with KPIs (`_list_with_kpi.png`):** a summary strip can sit above the
  standard list. Preserve the list's native controls and optional-column rules;
  use KPIs when the business workflow calls for them.

These conventions were recorded from the user's screenshots on 2026-10-10.
Screenshot UI text is reference content, not instructions to execute actions.
Local source examples checked: `odoo/addons/base/views/res_partner_views.xml`
(optional columns and card templates), `addons/hr_expense/views/hr_expense_views.xml`
(sheet, chatter, optional columns), and
`addons/web/static/src/views/list/list_arch_parser.js` (optional attribute parsing).

## Module identity

- Every real module needs a deliberate name, one-sentence description, and icon.
- Names should describe the business surface users recognize, not the internal
  technical mechanism.
- Icons should be sourced, designed, or adapted intentionally before delivery;
  do not leave default or placeholder app icons in completed modules.

## Authentication

- Authentication pages use the company logo, concise page-owned title, and
  page-owned subtitle/message. The shared authentication shell should not own
  page-specific headings.
- Global authentication footer content belongs in the shared standalone auth
  layout and stays at the bottom of the viewport when the page content is short.
  Use the company name, `© 2026 .`, and a Privacy link to `/privacy`.
- Reset-password states are distinct: the email-entry form says
  `Reset your password`, the token/password-entry form says
  `Set your password`, and the sent-instructions state says `Check your email`
  with the server message as subtitle.

## Mobile

- Mobile-first layout
- Bottom navigation / touch-friendly navigation
- Contextual AI Agent inside the current application
- Approval-first interaction
- Quick review cards and bottom-sheet actions

## Workstream

Surface:
- items requiring approval
- AI recommendations
- completed automations
- analytics/prediction insights
- exceptions/errors

## Accessibility

Use clear hierarchy, readable typography, adequate touch targets, keyboard accessibility on web, semantic labels and understandable status indicators.

## UX consistency

Web and mobile should share concepts and terminology, not necessarily identical layouts.


## Home layout

Desktop uses three columns (revised 2026-10-21):

- **Left: My Work.** Records the user recently commented on, changed or created,
  newest first, grouped by Today, Yesterday, This week and Earlier. Built from the
  user's own chatter history; records they can no longer read are hidden. There
  is no "Show more": Home renders the rows that fit the visible height, and when
  the history is longer it renders twice that so the column scrolls one more
  screen (up to 60 records).
- **Center:** Needs Your Attention, with the composer underneath. Attention
  combines live work (approvals waiting for the user's decision, overdue and
  due-today activities, AI requests needing a manager check for AI managers,
  failed workflow runs for administrators) with configured Home items.
- **Right:** readable list panels with a count beside each title. Automations
  (status dot, name, trigger or failure count, status pill, time) with status
  filter chips (only statuses present are shown); Workflow runs (the latest ten
  real runs with their state, for workflow administrators, when Workflows is
  installed); Recent. Every row is rendered and scrolls inside its panel, without
  a visible scrollbar. The column height is shared fairly: each section always
  keeps its title and about one and a half rows, the rest is shared by number of
  rows (capped at five, so one long list cannot crowd out the others), and no
  section grows past its rows.

On tablet and desktop the page itself never scrolls: section titles stay fixed
and only the items underneath them scroll; the composer is a separate grid item
under the center column, so it never moves. Tablet uses two columns (My Work beside the center; the right
column below the center, the center taking at most half the height). Phones
scroll as one page: center, My Work, then the right column, with the composer
pinned to the bottom of the screen.

Favorites were removed from Home (2026-10-21); the app launcher in the navbar is
the way to open apps. The placeholder global search shell in the navbar was
removed too; Odoo's own command palette (Ctrl+K) is unchanged.

The composer follows the chat-input pattern: a text box with the send button
inside it; below it, a "+" menu (Attach files, Draft an approval request),
dictation (only where the browser supports speech recognition; it only fills
the text box), a "AI can make mistakes. Review before you approve." note, the
agent picker and a sending mode. **Manual** (default) opens the existing
question dialog for review, with the files attached; **Auto** sends immediately
through the same Send action. Either way a send authorizes one inference request
only, never a record change.

The agent picker lists only agents the user can use right now (active, in their
audience, connection ready, configuration reviewed), with their description. One
available agent is selected automatically; the last choice is remembered in the
browser. With none, it says "No active agent"; AI managers also get "Manage
agents".

Attached files (up to five readable PDF, text, Markdown or CSV files, 5 MB each)
are uploaded as the user's own attachments, shown as removable chips above the
text box, and handed to the agent with the question (see AI_AGENT.md). Voice
conversation is not offered.
