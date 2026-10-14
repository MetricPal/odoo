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

## Agent chat audience

The agent form offers Company or Departments & users. Company includes active internal users with AI Agent user access and membership in the agent's company. Departments uses active employee membership in the exact selected departments, within the same company; membership changes apply immediately. Departments & users includes members of any selected department plus any individually selected users; either list can be empty, but at least one selection is required. Existing explicit audiences are preserved. Portal/public users are excluded. Chat access never expands data permissions or company boundaries. Department matching uses a privileged identity lookup only; employee data is not sent to the model. The module depends on HR for native department membership.

Response style is presented as four radio choices with short descriptions. These guide answer presentation; they do not certify model verification or change permissions.
