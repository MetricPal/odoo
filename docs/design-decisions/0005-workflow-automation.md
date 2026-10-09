# Workflows built on Odoo automation

Date: 2026-10-09

The Workflows brief broadens automation beyond approvals. Implement a dedicated
Workflows app with templates, a branching builder and run history.
Keep optional human decisions in Approval Center; do not duplicate its request
and reviewer models.

Use native Odoo server-action configuration for business operations and
base_automation for event subscriptions. Persist runs and append-only step logs
for waits, failures and recovery. Activate explicitly with a definition/action
fingerprint, test revision, actor and timestamp. Edits invalidate the preview.
The selected execution user and company govern business access.

Verified Odoo 20 uses unified ir.access records and OWL 3 explicit component
references. Native ir.actions.server.run elevates the runner, so the workflow
adapter invokes its permission check and internal dispatcher with the approved
user's environment. Native webhook actions are fire-and-forget; use a separate
tracked transport for workflow delivery status. Automatic events only enqueue
runs, keeping external calls out of the source record transaction.

Linked Approval Center requests gain narrow protections: fixed approvers and
minimum at submission, designated non-requester review, ordered decisions,
and no direct state/approver mutation. Other Approval Center requests preserve
their existing behavior.

The first module exposes eleven configuration recipes, not ready-to-send
business policies. Provider chat and AI generation require real integrations.
The UI names those limitations before activation. Remote delivery requires a
destination idempotency contract; uncertain outcomes require reconciliation.
