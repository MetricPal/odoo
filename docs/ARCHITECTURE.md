# Architecture

## Conceptual layers

1. Odoo ERP / business data
2. Identity, roles, groups, record rules, companies
3. Workflow/automation engine
4. AI orchestration and contextual agents
5. Analytics/prediction services
6. Approval and governance layer
7. Audit/event history
8. Web UX
9. Flutter mobile UX

## Separation of concerns

### Workflow
Deterministic business processes.

### AI
Reasoning, summarization, drafting, classification, recommendation and contextual assistance.

### Analytics
Metrics, forecasting, anomaly/risk scoring and predictive models.

### Governance
Policy evaluation, approval requirements, auditability and execution controls.

### Execution
The only layer allowed to cause real state changes. It must enforce authorization and approval requirements.

## Context model

Agent context should be derived from:

Identity
+ User Type
+ Role/Groups
+ Permissions/Record Rules
+ Company
+ Application
+ Current Record
+ Workflow State
+ Relationship to the record
+ Relevant history
+ Approved automation policies

## Web

Use an Odoo-compatible top bar and an Anchored Floating Command Panel for application navigation. Avoid a permanent left navigation drawer for this product concept.

## Mobile

Use a mobile-first dashboard and navigation model. Preserve the same mental model as web while adapting navigation to touch interaction.

## Evolution

Architecture decisions must be recorded in `docs/design-decisions/`.

### Reusable channel templates

`omni_template` owns scoped authoring records, ordered media and read-only record
rendering. It reuses native Odoo form/record-search/placeholder mechanisms without
granting technical-model access or changing connector code. A rendered copy is
content, not authorization: sending consumers must still apply their existing
capability, consent and frozen-approval checks. See
[Omnichannel templates](OMNICHANNEL_TEMPLATES.md).
