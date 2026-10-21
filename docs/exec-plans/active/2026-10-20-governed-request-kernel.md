# Governed request kernel and AI Agent prepared actions

Status: **Proposed, awaiting approval** (2026-10-20). Nothing in this plan is
implemented beyond the Approval Center groundwork listed under "Done".

## Objective

Give every module one governed path from "something prepared a change" to
"an authorized human approved it" to "it ran exactly once", and use it for AI
Agent gate 3: the agent prepares an action, a human approves it, the system
executes it with the requester's permissions.

## Done (groundwork, 2026-10-20)

- Approval Center protects status, decisions, targets and timestamps; only its
  actions change them (`_approval_trusted()` hook, server-side capability).
- No self-approval unless the category allows it; sequence and required
  approvers enforced; minimum frozen at submission; audit cannot be deleted.
- Workflows, Omnichannel and Social extend the trust hook instead of
  re-implementing request protection from scratch.
- Approved actions run once, inside a savepoint, with a durable failure audit.

## Scope

1. **Kernel fields on `approval.center.request`**: `source_model`,
   `source_res_id`, `payload` (JSON) and `payload_hash`, frozen at submission.
   A request with a source is a *governed request*.
2. **Execution adapters**: a registry keyed by `source_model`. An adapter
   implements `revalidate(request)` and `execute(request)`; Approval Center
   calls them instead of `getattr(record, action_name)`. Workflows, Omnichannel
   and Social register adapters and drop their `action_approve` overrides.
3. **AI Agent prepared actions** (gate 3): a curated list of action types
   (first: "draft a follow-up activity", "update a lead stage"). The agent
   returns a structured proposal; Odoo validates it against the action type's
   schema, creates a governed request with the frozen payload, and executes it
   after approval as the requester, never as a bot.

## Non-scope

- Writable MCP tools exposed to Hermes, autonomous execution, schedules.
- Changing how existing plain approval categories work for users.

## Design decisions

- Recorded in [ADR 0008](../../design-decisions/0008-governed-request-kernel.md).
- Approval stays human: an AI proposal is content, never authorization.
- Revalidation before execution: requester still active, company and record
  access unchanged, payload hash unchanged, target record unchanged since the
  proposal (write date or digest).

## Steps

1. Kernel fields and adapter registry in `approval_center`, with tests that a
   payload change after submission blocks execution.
2. Port Workflows to an adapter; delete its duplicated guards; run its suite.
3. Port Omnichannel and Social; run their suites and install harnesses.
4. AI Agent action types, proposal validation and governed request creation.
5. Review UI: the request shows the frozen payload as a readable diff.

## Verification

- Behaviour tests per step; full custom-module suite against the baseline.
- Security tests: forged payload, replay, cross-company, revoked requester,
  self-approval, double execution.

## Risks and rollback

- Adapter port changes three modules at once: port one module per release and
  keep the old overrides until its adapter passes the module's suite.
- Rollback: adapters are additive; reverting a module to its override restores
  the previous behaviour.
