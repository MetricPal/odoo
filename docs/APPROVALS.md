# Human Approval and Governance

## Principle

Humans supervise. Machines work.

## State-changing actions

Any action that changes, deletes, publishes, sends, edits, creates, confirms, cancels, pays, communicates externally, or otherwise affects real organizational/system state must pass the applicable approval policy.

## Approval object

A reviewable approval should contain:

- action
- target record(s)
- requested change
- reason
- evidence/context
- AI recommendation (if any)
- confidence/uncertainty where meaningful
- policy requiring approval
- requester/agent
- timestamp
- resulting audit record

## UX

Primary actions:
- Approve
- Reject
- Edit/Adjust
- Ask AI / Explain
- View evidence

The approval UI should make the decision understandable without forcing the user through the entire ERP record unless needed.

## Automation activation

A learned automation is not active merely because AI detected it.

Activation requires explicit user confirmation of the automation definition and its policy.

## Audit

Every approval and execution must be traceable.

## Odoo execution rule

When an approved request maps to existing Odoo behavior, execute it through the
module's public action method instead of writing final states directly. The
approval layer must enforce policy before calling the action and record the
audit result after the action completes or fails.
