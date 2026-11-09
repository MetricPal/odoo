# 2026-11-09 The assistant as the shared service of the ERP

Status: phases 1 to 3 done 2026-11-09 (`ai_agent` 20.0.1.16.0, 20.0.1.17.0, 20.0.1.18.0; boards 16 to 18 approved).
ADR 0014. Phase 4 (many agents working together): ADR 0015, built 2026-11-09 (`ai_agent` 20.0.1.19.0, boards 19 to 22).

## What the owner asked (2026-11-09)

The assistant is the primary and most important part of metric.io. It must serve **every automation** in the
system (workflows, approvals, omnichannel, social, marketing, scheduled jobs) **and** people's own commands
(Home, Discuss, chatter, Ask AI). There will be **many agents and many Hermes profiles**, used **at the same time**
by many automations and many people.

## Where it stands today (verified in this tree and on the live `odoo20` database)

Every caller already goes through one path: `ai.agent.run._queue()` (or `_queue_for_record()` for a run with no
person), then the `ai_agent.cron_runs` dispatcher submits to Hermes and follows the run. Callers: `ai_home`,
`ai_discuss`, Ask AI, `workflow_ai` (draft and the Ask agent step), `omni_ai`, `social_ai`, `marketing_intel_ai`,
`marketing_intel_assistant`, `marketing_intel_flow`. This is the right shape for a shared service; what is missing
is **capacity handling**. It was built for one person asking one agent.

| # | Problem | Where | Effect |
|---|---|---|---|
| 1 | A new question is **refused** once an agent has 2 runs in flight (`max_concurrent`, default 2). Nothing is queued. | `conversation.py` `_queue` | A workflow or a chat fails with "reached its request limit" whenever two other runs are slow. |
| 2 | `uncertain` and `stop_requested` runs count as in flight with no time limit. | `_queue` count | One stuck run can hold a slot until a manager clears it. |
| 3 | When Hermes is full it answers **HTTP 429** before it accepts anything, but Odoo treats a non-2xx POST as "acceptance uncertain". | `services/hermes.py` `request` | The run turns into "Needs manager check" and keeps holding an Odoo slot: a full Hermes makes things worse. |
| 4 | Hermes's run cap is **global for the whole gateway** (all multiplexed profiles share it), and the ERP Hermes template sets it to **2**. | `deployment/erp_hermes.py` (`max_concurrent_runs: 2`); Hermes `api_server.py` `_concurrency_limited_response` | All agents and profiles together get only two questions at once. Hermes's own default is 10. |
| 5 | A stop that Hermes never confirms leaves the run in "Stopping" forever. | `_cron_process` | Slot held (runs 4 and 5 on 2026-11-08 held both slots for 15 minutes while the free Gemini model was exhausted). |
| 6 | Hermes's failure reason is cut to **300 characters** and `error_message` is a one-line `Char`. | `_poll` | The useful part ("limit: 0 … Free Tier") was hidden. Same 300 cut on several setup errors in `configuration.py`. |
| 7 | No priority: a person waiting in a chat queues behind a batch of automation runs; the dispatcher takes the 10 oldest runs of all agents. | `_cron_process` | Interactive answers slow down when automations are busy. |
| 8 | No way to see load: how many runs are in flight per Hermes connection, profile and agent, how many wait, why they fail. | — | The owner finds out from a failed test. |

## Phases

### Phase 1: never block, never hide (backend only, no new UI)

1. **Keep the full reason.** `ai.agent.run.error_message` becomes `Text`; Hermes's reason is kept whole (it is
   already redacted by Hermes), capped only at a safety length (8,000 characters). Setup errors in
   `configuration.py` keep up to 2,000 characters. Same field and same place on the run form; no layout change.
2. **Queue instead of refusing.** `_queue` accepts the question as `queued` while the agent is at its concurrency
   limit; only the daily limits (agent, per person) and a queue-depth guard (50 waiting runs per agent) refuse.
   The dispatcher submits a queued run only when the agent has a free slot. Caller messages stay the same
   ("Queued" is already a status everywhere).
3. **Hermes busy = wait, not uncertain.** HTTP 429 on submission raises a new `HermesBusy`: the run goes back to
   `queued` with a short backoff (honouring `Retry-After`), one event "Hermes is busy; waiting for a free slot".
   Nothing was accepted by Hermes, and the idempotency key protects a repeat anyway.
4. **Slots that free themselves.** In-flight means `submitting`, `running`, `stop_requested`. `uncertain` no
   longer holds a slot (with item 3, Hermes itself is the safety net). A stop that Hermes has not confirmed within
   5 minutes ends the run locally as `cancelled` with "Hermes did not confirm the stop".
5. **Connection-wide limit.** `ai.agent.engine.max_concurrent` (default 10, matching Hermes) caps all agents and
   profiles on one Hermes connection, because Hermes's cap is per gateway. The dispatcher respects both limits.
6. **People first.** `ai.agent.run.priority`: `interactive` (a person asked: Home, Discuss, chatter, Ask AI and
   the "Draft with AI" buttons) or `automation` (no person: `_queue_for_record`, scheduled marketing). The
   dispatcher takes interactive runs first, then oldest first.
7. **ERP Hermes template** sets `max_concurrent_runs: 10`. The live `~/hermes-erp/config.yaml` needs the same
   edit and a Hermes restart (outside the repository).

Tests: queueing past the limit, dispatch respects agent and connection limits, 429 re-queues, stop timeout,
uncertain frees the slot, interactive before automation, full reason kept. Existing `ai_agent`, `ai_discuss`,
`workflow_ai`, `omni_ai`, `social_ai` tests stay green.

### Phase 2: one service contract for every caller (ADR 0014)

- One documented entry point, `ai.agent.run._ask(agent, prompt, *, origin=None, conversation=None,
  attachments=None, on_behalf_of=None)`: with a person it is interactive, without one it runs as the agent's
  assistant user and is automation. `_queue` and `_queue_for_record` stay as wrappers; all callers above move to
  it.
- `ai.agent.run.caller` (chat, home, chatter, workflow, omnichannel, social, marketing, …) for limits and
  reporting; per-caller daily limits so one automation cannot spend an agent's whole day.
- Automation runs counted apart from the per-person daily limit.
- Provider health: when a model answers "quota exhausted" or "model not found", stop sending to that model for a
  few minutes and fail its waiting runs fast with the full reason, instead of burning slots; optional fallback model
  per agent (check what Hermes v0.21 offers before building our own).

### Phase 3: see the load (new UI: mock first)

A capacity view in AI Agent (and a line in Home's System overview): in flight and waiting per Hermes connection,
profile and agent, oldest wait, failures by reason in the last 24 hours, and Stop on waiting runs. Mocks for
review before any code.

### Phase 4: many agents working together (ADR first)

Routing a person's command to the right department agent, and one agent asking another (delegation) within the
same permission rules (ADR 0012). Design and ADR only until the owner approves.
Proposed in ADR 0015: Odoo routes ("Ask" without choosing; the company agent picks among the agents the person may
ask, Odoo checks the pick) and an `ask_agent` Odoo tool lets an agent ask another on its May ask list, as the same
person, without blocking (a follow-up run merges the answer). Hermes `delegate_task` stays off. Mocks after approval.

## Not in this plan

Changing Hermes itself; new provider logins; anything that lets an agent act without an Approval Center request.
