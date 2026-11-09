# ADR 0015: Agents working together: routing and asking another agent

Date: 2026-11-09. Status: accepted with the recommended answers and built 2026-11-09 (owner: "Approved"; mocks:
AI Agent canvas boards 19 to 22, approved 2026-11-09).
Plan: `docs/exec-plans/active/2026-11-09-assistant-shared-service.md`, phase 4. Builds on ADR 0012 and 0014.

## Context

The assistant serves every automation and every person (ADR 0014), with one agent per department and a company
agent (ADR 0012). Two gaps remain:

1. **Who to ask.** A person must pick the right agent (Home, Discuss, chatter). Most people do not know that
   "carry over leave days" is the HR policy helper's question and "overdue invoices" is Finance's.
2. **Questions that cross departments.** An agent sees only its own department's data (assistant user ∩ person).
   "Can this customer get a discount, given their open invoices?" needs Sales and Finance.

Verified in Hermes v0.21: `delegate_task` (toolset `delegation`) starts child agents **inside the same profile**,
with the parent's tools, the same run key and no record in Odoo (`tools/delegate_tool.py`). It cannot reach another
department's profile, and its children are not limited by Odoo's capacity rules. Hermes has no cross-profile call.

## Decision (proposed)

### 1. Routing: "Ask" without choosing an agent

- A new entry point `ai.agent.run._route(prompt, *, caller, ...)`: the candidates are the agents the person may ask
  now (`ai.agent._chat_options()`, name and "What it helps with"). One candidate: it is used, nothing is asked.
  Several: the **company agent** is asked one short question (the candidates and the question; answer as JSON
  `{"agent": <id>, "why": "..."}`), with no tools and no business data.
- **Odoo checks the choice**: it must be one of the candidates, else the person chooses. The real question is then
  queued on the chosen agent through `_ask` (same rights, limits and priority as asking it directly).
- The person sees who answers and why ("Answered by HR policy helper: leave rules"), with **Change** to send the
  same question to another agent.
- Routing never widens access: a person is only routed to agents they could already pick.

### 2. One agent asks another, through Odoo

- A new Odoo tool on every profile, **`ask_agent(run_key, agent, question)`**, offered only to agents with a
  non-empty **May ask** list (chosen by AI Agent managers on the agent).
- Odoo checks: the target is on the asking agent's May ask list; the target is active; the target's audience
  includes the person who asked (in a chat) or the run has no person (automation, then the target's assistant user
  asks). The **child run** is queued through `_ask` as the same person (or assistant), `caller='agent'` ("Another
  agent"), with `parent_run_id`. Its rights are the target's usual ones (target assistant ∩ person): the asking agent
  gets nothing the person could not get by asking the target themselves.
- **Not blocking.** The tool returns at once ("Asked Finance; the answer will follow"). Waiting inside the tool would
  hold a Hermes slot while the child needs one, which deadlocks when capacity is full. When the child finishes,
  Odoo queues **one follow-up run** on the asking agent with the child's answer as reference data, in the same
  conversation, and that answer is what the person sees (Discuss, Home, the record that asked).
- **Limits.** One level only (a child cannot ask further), at most 3 children per run, children count against the
  target agent's limits and its "Another agent" source limit, and inherit the parent's priority.
- **Evidence.** The run form shows "Asked by <agent> for <person>" and links parent, children and follow-up; Activity
  can group by Asked from = Another agent.
- Hermes's own `delegate_task` stays **off** on Odoo-managed profiles: it bypasses Odoo's evidence and capacity, and
  splitting work inside one agent is not needed yet.

## Screens (mocks needed before code)

- **Home / Discuss:** an "Ask" entry that routes (alongside the agent picker, or replacing it: owner's choice), and
  "Answered by X · why · Change" on the answer.
- **Agent form:** a "May ask" list (other agents), AI Agent managers only.
- **Chat / run form:** "Asking Finance assistant…" while a child runs; parent, children and follow-up links.

## Alternatives considered

- **One agent with every department's data:** rejected in ADR 0012 (a person would see what the assistant sees).
- **The model routes alone, with every agent as a tool:** the model could pick an agent the person may not ask;
  Odoo must check the choice anyway, so Odoo owns the candidate list.
- **Hermes `delegate_task` across profiles:** not supported; children share the parent's rights and are invisible
  to Odoo.
- **A blocking `ask_agent`:** simplest answer flow, but a full Hermes deadlocks (parent holds a slot, child waits).
- **Show the child's answer directly instead of a follow-up:** cheaper (no second run) but the person gets two
  partial answers; offered as an option per agent if the owner prefers.

## Consequences

- A routed question costs one extra short run on the company agent (none with a single candidate).
- A delegated question costs the child run and one follow-up run; answers take longer than a direct question.
- New fields: `ai.agent.may_ask_ids`, `ai.agent.run.parent_run_id`, new caller `agent`; new tool `ask_agent`.

## Answers (owner, 2026-11-09: the recommended ones)

1. Routing entry: an extra "Ask" next to the agent picker (recommended to start), or "Ask" as the default with the
   picker behind it?
2. Delegated answers: merged by a follow-up run (recommended), or the child's answer shown as is?
3. Which agent routes when a company has no company agent: refuse routing (recommended), or the first department
   agent the person may ask?
