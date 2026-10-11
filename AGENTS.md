# AGENTS.md — Project Map

You are working on an AI-native ERP based on Odoo 20 Community Edition.

## Non-negotiable principles

1. Humans supervise. Machines work.
2. Any action that changes, deletes, publishes, sends, edits, or otherwise affects real organizational/system state requires explicit human approval unless the approved automation policy explicitly defines an allowed execution path.
3. Never infer authorization from observed user behavior. Observed behavior is not permission.
4. Respect Odoo user type, groups, record rules, company boundaries, portal/public visibility, and application context.
5. Do not assume Odoo 18/19 behavior is valid in Odoo 20.
6. Before implementing Odoo-specific code, verify the actual Odoo 20 Community source/API/documentation.
7. Prefer existing Odoo mechanisms over duplicating core behavior.
8. Keep AI, deterministic workflows, analytics/prediction, authorization, and execution as separate concerns.
9. Every meaningful implementation must include tests appropriate to the layer.
10. Update documentation when architecture or behavior changes.

## Progressive disclosure

Do not turn this file into an encyclopedia. Use it as a map.

Read:
- Product: `docs/PRODUCT.md`
- Architecture: `docs/ARCHITECTURE.md`
- Odoo: `docs/ODOO20.md`
- AI: `docs/AI_AGENT.md`
- Approvals: `docs/APPROVALS.md`
- Security: `docs/SECURITY.md`
- Design: `docs/DESIGN.md`
- Channel UX: `docs/CHANNEL_UX_NOTES.md` for channel/provider work
- Quality: `docs/QUALITY.md`

For implementation tasks, also inspect the relevant skill in `.codex/skills/`.

## Task loop

Research → Plan → Implement → Test → Review → Document → Report.

Do not silently make broad architectural changes while implementing a narrow task.

## Approval boundary

Prepare/draft/analyze/recommend may be automated.

State-changing execution must be human-gated according to `docs/APPROVALS.md` and the current policy.

## Completion

A task is not complete merely because code compiles. Verify behavior, tests, security/permissions, UX implications, and documentation.
