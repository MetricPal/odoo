# Workflows

Build and monitor supervised business automations in the **Workflows** app,
available from the app menu to administrators. Internal approvers continue to
use Approval Center.

Use **Overview** and **Run history** in Odoo's top navbar.
The standard **New** button beside the Overview breadcrumb opens a workflow draft.

## Start here

1. Install `workflow_center`. The shared workflow worker is initially off.
2. Choose a template, or choose a business document and start blank.
3. Set **When** the workflow starts and the optional **If** filter. Choose the
   company and the internal user whose permissions should apply.
4. Select each step and open **Step settings**. For Create record, choose its document and fields to set. For other business
   actions, use **Configure action** to select the actual field, activity, email template,
   record creation or code in Odoo's standard configuration screen.
5. Resolve each item under **Before you activate**. Run **Preview / run** on a
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
