# ADR 0012: Department AI assistants, Hermes profiles managed from Odoo, Odoo tools

Date: 2026-11-07. Status: accepted (owner); implementation planned in
`docs/exec-plans/active/2026-11-07-ai-agent-control-panel.md`. Supersedes parts of ADR 0007.

## Context

ADR 0007 made `ai_agent` a supervised read-and-draft assistant: one hand-provisioned, tool-free Hermes profile;
Odoo sends a fixed slice of business data with each question, read as the requester; no bot user ever reads data.
The owner wants `ai_agent` to be the control panel of Hermes: agents created and configured from Odoo, agents that
work with Odoo data inside permissions, department managers configuring their own agents, and agents taking part
in workflows. An agent must not stop working because the person it was set up with leaves the organisation.

## Decision

1. **AI assistant users.** Each department has an Odoo user that agents act as ("HR Assistant"), plus a company
   assistant. It has no password and cannot log in; its groups are its role and are managed by administrators.
   This replaces ADR 0007's "a powerful bot user is never used to retrieve context".
2. **Permissions.** In a chat, an agent may use only data that both the assistant user and the person asking may
   read (record rules and field groups for both). In workflows and scheduled runs there is no person: the
   assistant user alone. The agent's own scope (models and fields chosen for it) narrows both further.
3. **Hermes profiles.** One Hermes profile per department plus one company profile, created, updated and archived
   from Odoo through the Hermes management API. An agent uses its department's profile; a manager may give an
   agent its own profile when it needs different external tools or isolation. Agent instructions and model are
   sent per run, so agents share a profile. Profiles are served by one multiplexing gateway
   (`gateway.multiplex_profiles`, paths `/p/<profile>/v1/...`, one `API_SERVER_KEY` per profile).
4. **Odoo tools.** Odoo offers an MCP server configured on every profile (URL and a bearer token per profile).
   This replaces ADR 0007's tool-free profile. Hermes does not tell an MCP server which run a call belongs to (its
   identity header is fixed per server or profile, MCP connections are shared per profile, and the run API has no
   tool metadata; verified on Hermes v0.21.3). Each run therefore gets a random one-run key in its instructions,
   every Odoo tool requires it, and Odoo accepts it only from the same profile's token while the run is in
   progress. Tools are read-only first; then prepare-only, where every change becomes an Approval Center request
   (ADR 0008). Terminal, file and browser-control toolsets are never offered.
5. **Department control.** Department managers (Employees) and department AI admins chosen by an administrator
   change their department's agents, profile persona, skills and enabled tools without approval. Changing an
   assistant user's groups stays with administrators. Every change is recorded.
6. **Hosting.** Local and remote Hermes are both supported. The management API is Hermes's dashboard API, which is
   not versioned: Odoo records the tested Hermes version and checks it on connection.

Kept from ADR 0007: Odoo owns identity, scope and evidence; durable run claims and audit; persistent Hermes memory
off; provider logins stay in Hermes's own setup; instructions and skills are never authorization.

## Alternatives considered

- **One profile per agent:** cleanest isolation, but the number of profiles, keys and processes grows with agents;
  kept as the exception.
- **Agents act as a person (a department manager):** rejected; the agent stops when that person leaves.
- **Assistant user alone in chats:** rejected; anyone allowed to chat would see what the assistant sees.
- **Pre-sent business data only (ADR 0007):** the data does not depend on the question; replaced by tools.
- **Per-run MCP connection or per-run profile:** not supported by Hermes without changes, or too heavy.

## Consequences

- An assistant user with broad groups is powerful in workflows; administrators give it only what the department's
  agents need.
- The one-run key lives in the run's instructions: a model could repeat it in its answer. It is useless after the
  run ends and only works from the same profile.
- Department profiles share Hermes sessions; memory stays off.
- Enabling multiplexing changes the default Hermes profile's gateway; existing hand-made profiles are migrated
  (the `odoo-internal` profile becomes the company profile).
