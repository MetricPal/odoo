# ADR 0008: Approval Center as the governed request kernel

Date: 2026-10-20. Status: groundwork implemented; kernel and adapters proposed.

## Context

Workflows, Omnichannel and Social each protected "their" approval requests by
overriding `create`, `write`, `unlink`, `action_approve` and `action_refuse` on
`approval.center.request` and `approval.center.approver`. Plain requests had no
protection: a requester could set `state='approved'` through RPC, add or
approve their own approver lines, approve their own request, and delete the
audit trail by deleting the request.

## Decision

Approval Center owns the governance rules for every request:

- Status, decisions, targets and timestamps change only through its actions,
  which carry a server-side capability (`approval_internal`). Integrations
  extend `_approval_trusted()` with their own capability.
- Business content is frozen after submission; cancel returns the request to
  draft so it can be edited and resubmitted.
- Requesters cannot decide on their own request unless the category enables
  "Allow Self-Approval". Administrator decisions outside the approver list are
  recorded as overrides.
- Sequential order and required approvers are enforced; the minimum is frozen
  at submission.
- Audit entries are append-only and requests with history cannot be deleted.
- Approved actions must be `action_*`/`button_*` methods of the category's
  target model, run once, inside a savepoint; failures are audited.

Integrations keep their stricter rules (frozen payloads, expiries) through
`_check_can_review()` and their existing overrides until they move to the
adapter registry described in the active plan.

## Consequences

- Existing plain requests keep working; users who relied on editing submitted
  requests must cancel first.
- `approval_center` now has behaviour tests; the integration suites ran
  unchanged against the hardened base.
