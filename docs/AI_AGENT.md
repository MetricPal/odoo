# AI Agent Contract

## Purpose

Provide contextual AI assistance inside each ERP application while maintaining strict authorization and human governance.

## Contextual agents

Examples:
- Sales Agent
- Inventory Agent
- Finance Agent
- Recruitment Agent
- HR Agent

They share an orchestration architecture but receive application-specific context and tools.

## Capabilities

AI may:
- explain
- summarize
- search permitted data
- analyze
- draft
- recommend
- predict
- prepare actions
- propose automations

## Learned behavior

The agent may detect repeated user behavior and propose an automation.

Example:
"You review overdue opportunities every Monday. Would you like me to prepare this review automatically?"

The proposal must show:
- trigger
- scope
- data accessed
- proposed actions
- schedule
- approval requirement
- rollback/disable path where applicable

## Critical rule

Observed behavior != permission.

The agent must never escalate its own permissions because it has observed a repeated action.

## Agent output

Prefer:
What happened?
Why?
What do you recommend?
What needs my approval?

## Limits, retries and record selection

- Each agent has a daily request limit and a per-person daily limit (default 20;
  0 disables the per-person limit). Days are UTC.
- Status checks that fail are retried automatically with backoff. Only an
  unconfirmed submission needs a manager check. A definite rejection (HTTP 4xx
  other than 408/429) fails without retry.
- If the agent configuration or the requester's access changes while an answer is
  being prepared, the answer is discarded, not published.
- Each data scope chooses which records come first when more match than its
  limit: recently updated (default), newest or oldest. Sources share the context
  budget, best-matching paragraphs first.
- "Ask AI" on an approval request opens the question dialog prefilled with what
  the user can already see on the request. Nothing is sent until they click Send,
  and the assistant cannot approve or refuse.
- Questions can carry up to five attached files (readable PDF up to 50 pages, or
  UTF-8 text, Markdown or CSV; 5 MB each), from Home or the question dialog. Only
  files the requester uploaded for that question are accepted. Odoo extracts the
  text, sends it with the question as untrusted reference content within the
  context budget (up to 12,000 characters per file), and links the files to the
  run, so only people who may read the run may read them. Hermes receives text,
  never the files themselves; images and other formats are refused with a clear
  message.

## Agent chat audience

The agent form offers Company or Departments & users. Company includes active internal users with AI Agent user access and membership in the agent's company. Departments uses active employee membership in the exact selected departments, within the same company; membership changes apply immediately. Departments & users includes members of any selected department plus any individually selected users; either list can be empty, but at least one selection is required. Existing explicit audiences are preserved. Portal/public users are excluded. Chat access never expands data permissions or company boundaries. Department matching uses a privileged identity lookup only; employee data is not sent to the model. The module depends on HR for native department membership.

Response style is presented as four radio choices with short descriptions. These guide answer presentation; they do not certify model verification or change permissions.

## Answers for other apps (2026-10-21)

- A run can name the record that asked for it (`origin_model`, `origin_res_id`).
  When the run finishes, that record's `_ai_agent_finished(run)` is called with
  the requester's permissions, inside a savepoint; a failure is recorded as a run
  event and never changes the run. Only a record the requester may change can ask.
- `workflow_ai` (installs with Workflows and AI Agent): "Draft with AI" in a new
  workflow creates a draft and asks the agent for a name, a trigger and suggested
  steps. Only the name and a valid trigger are applied; steps are shown as a
  suggestion for the administrator to build. Nothing is activated.
- `omni_ai` (installs with Omnichannel and AI Agent): "Draft reply with AI" on a
  reply draft sends the recent conversation (customer text marked as untrusted)
  and puts the answer in the draft if it is still empty, otherwise beside it with
  "Use this text". The reply is still edited, submitted and approved as before.
- `social_ai` (installs with Social and AI Agent): "Draft with AI" on a post
  draft writes from a short brief or adapts existing text to the platform's
  limit (from the connector's capability list); "Draft reply with AI" on a
  comment or message starts a reply draft (platform text marked as untrusted);
  campaigns adapt every version; "Summarize activity" on an account summarizes
  the last 7 days for team members. Text fills an empty draft or is shown as a
  suggestion; nothing is submitted or published by the agent.
- `ai.agent._chat_options()` lists the agents the current user can ask now, for
  pickers in other apps.
