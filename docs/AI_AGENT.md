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
