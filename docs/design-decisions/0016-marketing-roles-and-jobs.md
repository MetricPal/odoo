# ADR 0016: Marketing roles (Head of department, Senior, Junior) and assistant jobs

Date: 2026-11-09. Status: accepted (owner, 2026-11-09: review chain yes); roles, review chain and role panels built 2026-11-09
(`marketing_intel_team`); assistant jobs (point 5) and the Jobs and health page wait for plan M4. Plan:
`docs/exec-plans/active/2026-11-09-marketing-workspace.md`. Builds on ADR 0008 (Approval Center), ADR 0012
(department assistants), ADR 0014 (shared service) and ADR 0015 (agents working together).

## Context

Marketing has two groups (User, Administrator) and panel views picked automatically (Marketer, Advisor,
Manager). The owner wants three working roles, each with its own perspective, and the Marketing assistant,
workflows and automations doing part of the daily work, followed by people.

## Decision (proposed)

1. **Groups**: Marketing / Junior ⊂ Senior ⊂ Head of department; Administrator implies Head of department. The
   existing User group becomes Junior (same rights, so nothing breaks); existing users are not promoted
   automatically.
2. **Review chain**: a junior's campaign, post, email or design goes to a **senior review** (accept / request
   changes) before the existing release approval. A senior may release within **limits set by HOD** (budget,
   audience size, channels); above them, HOD approves. All through Approval Center, so every decision is recorded.
3. **Perspective**: the control panel's role view follows the group (Junior: My day, Senior: My team, HOD:
   Department); people can still adjust their own view.
4. **The department is the team** (owner, 2026-11-09): the department marked as the marketing department; its manager
   is the head of department, its employees the team, each employee's manager reviews their work; limits live on the
   department. The department's AI assistant user (ADR 0012) is the Marketing assistant that runs jobs.
5. **Assistant jobs**: recurring work is a `workflow_center` workflow with an Ask agent step, run as the Marketing
   assistant user (`as_assistant`, caller Marketing), with an owner who receives its output. Jobs only prepare:
   drafts, suggestions, reports, to-dos. Sending and publishing stay with people and the review chain.
6. **Health**: a job is *healthy* (last run fine), *waiting* (output waiting for a person), *failing* (last run
   failed; owner gets a to-do after two failures in a row), or *paused*. Juniors see their jobs, seniors their
   team's, HOD all.

## Alternatives considered

- **Roles only for dashboards, no review chain**: simpler, but juniors could release on their own.
- **Assistant sends on its own within limits**: faster, but against "Humans supervise. Machines work." for
  outward actions; kept for later, per job, if the owner wants it.
- **Jobs in a new scheduler**: `workflow_center` already has schedules, approvals, history and the Ask agent step.

## Consequences

- One more review step for juniors' work; seniors carry it.
- Existing marketing users become Juniors until an administrator promotes them.
- New panel blocks per role; the Jobs and health page is new UI (mock first).
