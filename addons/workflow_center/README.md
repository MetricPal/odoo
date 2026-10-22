# Workflows

Build and monitor supervised business automations in the **Workflows** app,
available from the app menu to administrators. Internal approvers continue to
use Approval Center.

Use **My workflows** and **Run history** in Odoo's top navbar. Click the
**Workflows** app name to return to the overview.
**My workflows**, beside the Workflows app name, lists existing workflows and
opens their builder from either native list rows or kanban cards. Switch views
using Odoo's standard view switcher. Extra list columns are optional and hidden
by default. Kanban always shows Draft, Active, and Pause in that order, including empty
columns. Cards and columns cannot be dragged;
status changes require the existing builder actions.
**New** in Overview, list, or kanban opens the native workflow form. The
**Describe what should happen** panel, document selector, and **Start blank**
button sit inside its white sheet for unsaved workflows. **Start blank** fills
Document and Description on that same unsaved form without navigation or saving.
It does not infer triggers or steps from prose. **Open builder**, immediately after **New** in the form toolbar, validates and
saves the draft before opening its steps. The panel is hidden for saved workflows. The native chatter sits alongside the
form on wide screens, using Odoo's normal responsive form layout.
The Workflows overview has a native Kanban/List switcher (Kanban by default).
Both views share the application search panel and top search/filter/group controls.
List shows Template, Application, and Category; extra columns are hidden by
default and available through the column selector. Opening a card or row starts
a draft from that template. New opens a blank workflow form.

The overview has a native left search panel listing Applications from
the card badges, with counts and an All option. Selecting an application filters
the cards and combines with the top search controls. The kanban renderer sits directly beside the search panel, without form-sheet
wrappers, and scrolls below the fixed toolbar and search controls. The Workflow guide, including
**Every workflow is When → If → Do**, appears in the builder directly below
the selected-step settings. Templates use Odoo's wrapping kanban
layout and article cards, without a gallery heading or template count. Use Odoo's search bar for template text,
Filters for recipe categories, and Group By for Category or Application. Clear
the search facets to see all recipes. A read-only catalog view supplies native
search metadata; it does not create or activate workflow definitions. The listing retains the existing administrator and company access scope.
The overview retains templates; the creation panel lives inside the new workflow form sheet.

Run history uses native Odoo List/Kanban views and pagination (80 runs per list
page). Search by record, workflow, or step; filter by status, preview/live runs,
uncertain delivery, or start date. Group by workflow, status, preview/live,
start date, or company when permitted. Additional list columns are optional and
hidden initially. Kanban groups runs into Running, Waiting, Failed, Done, and Stopped, in that
order, including empty columns. Run cards cannot be dragged to change status. Open a run to
inspect its logs and use the existing confirmed recovery controls; **Open
workflow** returns to its builder. Historical Run history URLs redirect to this
native action, retaining the existing access and company rules.

## Start here

1. Install `workflow_center`. The shared workflow worker is initially off.
2. Choose a template, or choose a business document and start blank.
3. Set **When** the workflow starts and the optional **If** filter. Choose the
   company and the internal user whose permissions should apply.
4. Select a step to edit its settings directly in the right-hand panel. Use the
   native action row at the top of the right panel: **Save**, **Discard**,
   **Remove step**, then extra actions such as **Configure action**. Remove step
   uses secondary styling; a horizontal divider separates the row from settings. For Create record, choose its document and fields to set. For other business
   actions, use **Configure action** to select the actual field, activity, email template,
   record creation or code in Odoo's standard configuration screen.
5. Review workflow setup by selecting the **When** starting-point card. Run **Preview / run** on a
   real record in Preview mode. No business action is performed during preview.
6. Review the configured effects and click **Activate**. This explicitly
   authorizes matching future events and enables the shared worker.
7. Use **Run history** to inspect steps, errors and pending approvals. Pause a
   workflow to stop new triggers and suspend its unfinished runs.

Preview evaluates conditions against current data, without applying preceding
actions or elapsed time. It is a plan inspection, not proof that a provider will
deliver a message. Run mode queues the active workflow for the worker.
A workflow's configured actions and scope are its approved automation policy;
an extra per-record approval step is optional.

## Templates

Templates are starting points. Built-in templates come with the app (read-only;
archive them to hide them). **Save as template** on any workflow keeps a hidden
copy that can be edited in the builder (**Edit template**) but never activated;
starting from a template creates an independent draft that still needs a
preview and activation. Templates are grouped by **What it does** (Reminders,
Data updates, Create records, Scheduled, Integrations, Approvals, Other — one
colour each) and by application. Settings administrators manage them.

## Working from the lists

My workflows (list and kanban) offers **Preview / run**, **Activate** (shown
only when the current version has a successful preview and no setup issue;
otherwise **Before activation** says what is missing), **Pause**, **Runs**,
**Duplicate** and **Save as template**, with run and failure counts.

**Run history** lists every run: live runs started by the trigger or by Run,
and previews ("Preview only"). Open a run to see its steps, the current step,
waits, errors and approvals, and to retry, skip or stop it.

## Builder

The step palette explains each step and shows an example on hover. A click
adds the step after the selected step, or at the end of the main path (the
hint above the palette says where); when the main path ends with a branch,
select the step it should follow first, or drag it onto that step. Branches
draw a split into Yes and No and a join where the paths continue together.
The preview dialog asks for one existing record of the workflow's document
(**Test on**); **Run now** is offered only while the workflow is active.

## Triggers and steps

Triggers: record creation, watched-field changes, stage/status changes (watched
field plus filter), date fields with an offset, hourly schedules, manual runs
and incoming webhooks. Manual workflows add **Run workflow: [name]** to the
source document’s Action menu after activation; pausing removes that entry.
This is an explicit workflow entry point, not an override of existing business
buttons such as Confirm Order. Odoo `base.automation` handles record/date/webhook
events. A webhook definition shows Odoo's generated URL after activation and
accepts the source record ID as `_id`; its model is fixed by the workflow.
Treat the webhook URL as a credential and use HTTPS at the deployment boundary.

Actions reuse native Odoo configuration for record updates,
activities, followers, email/Odoo messages and Python code.
Create record has typed field mappings: choose the target document and set its
required values from fixed entries, source fields or the source document itself.
An optional link stores the new record on the source document.
Conditions stop nonmatching records; branches have explicit Yes/No paths;
waits resume at a duration or date field. For each record executes its
configured action over a related list (maximum 500 records).
Email actions queue through Odoo; a successful workflow step does not certify
downstream mail-server delivery.

Template drafts contain suggested steps, not fabricated customer data or
preauthorized messaging. Missing business apps are identified on their cards.
Business-specific conditions, recipients, mail templates, mappings and approval
types must be configured. There are eleven recipes, including invoice reminders,
lead assignment, onboarding, low-stock review and purchase approval.

**AI drafting and provider chat are not connected.** A description is saved with
a draft; it is not passed off as AI-generated logic. The lead recipe includes a
WhatsApp step but cannot activate until a workflow provider integration exists,
or the administrator replaces it with email/Odoo messaging. This module does
not implement the future WhatsApp provider or bypass Omni-Channel authorization.

## Approval steps

Choose a review-only Approval Type. Its configured people, order and minimum
determine the reviewers. Requests retain their approver list and required count
when they start. Later changes to the type do not weaken an existing request.
Changes to the source record or its related lines while review is pending stop
the run and require a fresh review. The requester cannot decide their own request;
designated reviewers must act in
the required order, and refusal stops the run. Decisions and step history are
auditable. Direct writes to linked request states and approver lines are denied.

This reuses existing Approval Center screens. It does not add unsigned approval
links, Telegram approval buttons, absence delegation or generic record locking.
Those screenshot concepts need separate integration with the affected business
actions; they are not implied by adding an optional approval node.

## Execution and recovery

Only Settings administrators can configure, activate, pause or recover runs.
All metadata is company scoped. Execution explicitly uses the selected internal
user and company and checks business access; it does not inherit the automation
callback's superuser privileges. Python code is trusted administrator-authored
configuration and must itself respect the approved scope.

Automatic triggers queue durable runs; they do not perform external calls
inside the source record's transaction. The worker processes due runs and
scheduled records in batches. Only one unfinished live run per workflow and
record is admitted. Paused workflows do not advance. Stop unfinished runs
before editing their steps; a changed definition requires another preview and
activation. Changed action configuration causes a run to stop for review.

Native database action failures roll back that step. Failure policy may stop,
retry after five minutes (bounded attempts), or log and continue. Approval and
logic cannot be skipped. Run controls record explicit retry, skip and stop
decisions. Run history and step logs cannot be edited or deleted.

Outgoing webhooks use the native action's URL and selected fields but a tracked
HTTPS transport. Deployment must set `WORKFLOW_WEBHOOK_HOSTS` to a comma-separated
list of approved hostnames. The transport disallows credentials in URLs,
non-HTTPS, non-443 ports, redirects and private/reserved addresses. Connections
are pinned to a validated public IP with certificate hostname validation.
Response bodies and credentials are not logged.

The destination must handle the stable `Idempotency-Key` header to prevent
duplicates across worker crashes. Exactly-once remote delivery cannot be
guaranteed by a database transaction. HTTP failure or uncertain delivery stops
automatic retries; an administrator must check the destination before using
**Retry after checking delivery**. Arbitrary Python integrations likewise need
their own idempotency and transaction discipline.

## Verification

Run on a disposable database:

```sh
python odoo-bin -d workflows_test --addons-path=addons -i workflow_center \
  --without-demo --test-enable --test-tags=/workflow_center --stop-after-init
```

Chrome and websocket-client are required for the desktop/mobile browser tests.
Transport tests use synthetic responses; no external webhook is sent.

The builder places Preview / run and Activate (Pause for active workflows) in
the native top-left control-panel button area. Select the **When** starting-point
card to show workflow settings in the right-hand editor; there is no separate Settings button. Add a step uses the left Odoo search-panel layout and
native draggable resize handle. The workflow canvas and right chatter-style guidance area
scroll independently below that toolbar. The right content shows the selected step’s native form; Workflow guide appears
only when neither a step nor the starting point is selected. The
activation checklist and insertion hint are removed; activation validation remains.

The Add a step panel explains both ways to add steps: click a palette item or
drag it onto the canvas.
Drop on a step to insert after it, or on the When card to insert at the beginning.
A blank-canvas drop inserts after the current selection. Step cards have a borderless × with red text and a transparent background;
the right-panel Remove step action is a secondary button. Both use the
existing deletion confirmation and branch-reference checks. Switching selections
saves pending valid edits through Odoo’s form controller; validation failures keep
the current editor open. Active workflows remain read-only until paused.

Only the selected canvas card has a highlighted border, including the When card.

The builder shows the workflow status beside its name in the native top bar;
the canvas has no duplicate workflow title or document breadcrumb.
