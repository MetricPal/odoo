# ADR 0014: The assistant is the shared service of the ERP

Date: 2026-11-09. Status: phase 1 accepted and built (owner, 2026-11-09); phase 2 **proposed, for owner review**.
Plan: `docs/exec-plans/active/2026-11-09-assistant-shared-service.md`. Builds on ADR 0012 and 0013.

## Context

The owner (2026-11-09): the assistant is the primary and most important part of metric.io. It serves every
automation (workflows, approvals, omnichannel, social, marketing, scheduled jobs) and people's own commands (Home,
Discuss, chatter, Ask AI), with many agents and many Hermes profiles used at the same time.

Every caller already goes through `ai.agent.run` (`_queue`, `_queue_for_record`) and the `ai_agent.cron_runs`
dispatcher. That path was built for one person asking one agent: it refused questions past an agent's concurrency
limit, treated a full Hermes (HTTP 429) as "acceptance uncertain", let stuck runs hold slots, cut Hermes's failure
reason at 300 characters, and gave automations and people the same place in line. Hermes caps runs per gateway (all
multiplexed profiles share one cap; verified in Hermes v0.21 `api_server.py`), and the ERP Hermes template set that
cap to 2.

## Decision

### Phase 1 (built)

1. **A question waits; it is not refused.** Past the agent's concurrency limit a run stays `queued`. Refused only
   by the daily limits or a full queue (50 waiting runs per agent). A run that waited 30 minutes fails with a reason
   and its caller is told.
2. **Two limits, both enforced by the dispatcher.** The agent's "Requests at the same time" and the Hermes
   connection's `max_concurrent` (default 10, all agents and profiles on that connection). In flight means
   `submitting`, `running`, `stop_requested`; `uncertain` no longer holds a slot.
3. **A full Hermes means wait.** HTTP 429 on a submission raises `HermesBusy`: the run goes back to the queue with
   backoff (honouring `Retry-After`). Hermes checks its cap before it reserves the idempotency key, so nothing was
   accepted and the same request key may be sent again.
4. **Stops end.** A stop Hermes has not confirmed after 5 minutes ends the run locally (`cancelled`, with the
   reason).
5. **People first.** `ai.agent.run.priority`: `interactive` (default) or `automation` (`_queue_for_record`, the
   marketing flow AI split and the campaign learning note). The dispatcher sends interactive runs first.
6. **Nothing hidden.** `error_message` is a `Text`; Hermes's reason is kept up to 8,000 characters (Hermes has
   already redacted it). Setup errors keep up to 2,000.
7. **ERP Hermes** is provisioned with `max_concurrent_runs: 10`.

### Phase 2 (proposed)

1. **One entry point.** `ai.agent.run._ask(agent, prompt, *, origin=None, conversation=None, attachments=None,
   on_behalf_of=None, caller)`. With a person: their rights and the assistant's (ADR 0012), interactive. Without:
   the agent's assistant user, automation. `_queue` and `_queue_for_record` remain as wrappers; every caller moves.
2. **Caller.** `ai.agent.run.caller` (chat, home, chatter, ask, workflow, omnichannel, social, marketing, …) for
   reporting, and optional per-caller daily limits per agent, so one automation cannot use an agent's whole day.
   Automation runs no longer count against a person's daily limit.
3. **Provider health.** When Hermes reports a provider quota or "model not found" failure, Odoo stops sending to
   that model for a few minutes and fails waiting runs on it at once with the full reason, instead of using slots on
   requests that will fail. A fallback model per agent only if Hermes v0.21 has no fallback of its own (to check).
4. **A load view** (needs an approved mock): in flight and waiting per connection, profile and agent; oldest wait;
   failures by reason; Stop on waiting runs.

## Alternatives considered

- **Raise the per-agent limit only:** does not fix the shared Hermes cap, the 429 handling or stuck slots.
- **Queue in Hermes:** Hermes refuses past its cap instead of queuing; Odoo owns identity, evidence and priority, so
  the queue belongs in Odoo.
- **A job queue module (queue_job):** extra dependency for a queue we already have (`ai.agent.run` states and the
  runs cron).

## Consequences

- Callers see `queued` for longer under load instead of an error; their "waiting" text stays the same.
- A run cancelled locally after an unconfirmed stop may still finish in Hermes; its answer is never published (the
  run is already terminal), and Hermes's own cap still protects it.
- The live `~/hermes-erp/config.yaml` must match the connection limit (`max_concurrent_runs`).
