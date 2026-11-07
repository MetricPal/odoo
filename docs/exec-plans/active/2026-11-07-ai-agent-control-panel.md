# 2026-11-07 AI Agent as the Hermes control panel

Status: phase 0 done (owner review of mocks pending). ADR: `docs/design-decisions/0012-ai-agent-department-assistants.md`.
Mocks for review: https://claude.ai/artifact/9Uw7Mzz6KG8FXCZ3m6mqtd (department AI tab, Hermes profile, agent,
workflow Ask agent step). No code yet; UI is built only from approved mocks.

## Objective

Make `ai_agent` the control panel of Hermes Agent: administrators create agents, manage their models, tools and
services from Odoo; Odoo users and departments use agents that can work with Odoo data within permissions; agents
take part in workflows. Department managers and department admins configure their own agents.

## Decisions (owner, 2026-11-07)

- **Department profiles.** Each department has one Hermes profile, plus one company-wide profile. An agent uses its
  department's profile; a manager can give an agent its own profile when it needs different external tools or full
  isolation.
- **AI assistant users.** Each department has its own Odoo user, for example "HR Assistant", plus a "Company
  Assistant". Agents act as this user, never as a person, so an agent keeps working when a person leaves or their
  account is suspended. Its permissions are normal Odoo groups, managed by administrators.
- **Chat permissions: assistant and person.** In a chat, the agent can only use data that both the assistant user
  and the person asking may see. In workflows and scheduled runs there is no person: the assistant user alone.
- **Department changes need no approval.** Department managers and department admins change their department's
  agents, instructions, skills and tools directly. Changing the assistant user's permissions (groups) stays with
  administrators.
- **Hosting.** Local and remote Hermes are both supported.
- **First tools.** Read-only first (search records, read a record, a record's activities and messages), then
  prepare-only (draft note or message, draft activity, proposed field change). A proposed change becomes an
  Approval Center request; nothing is written without a person approving it.

These replace ADR 0007's "tool-free profile" and "no bot user reads data" rules: a new ADR records them (phase 0).

## Scope

- Hermes profiles created, updated and archived from Odoo: persona, default model, skills, toolsets, MCP servers.
- AI assistant users per department and company; department AI roles.
- Odoo tools for agents (an MCP server in Odoo), with the permission rules above.
- An "Ask agent" step in Workflows.
- A view of each profile's tools and services (MCP servers, toolsets, scheduled jobs).

## Non-scope

- Hermes persistent memory stays off (it would be shared inside a department profile).
- Messaging gateways in Hermes (Telegram, Slack, ...): Omnichannel stays the only channel to customers.
- Agents writing records directly: every change goes through Approval Center.
- Customer-facing (portal, website) agents.
- Provider logins (API keys, OAuth): they stay in Hermes's own setup screen, opened from Odoo as today.

## Affected modules

- `ai_agent` (major version), `workflow_ai` (Ask agent step), `workflow_center` (step kind hook),
  `approval_center` (adapter for agent proposals), `ai_home` (agent picker unchanged).

## Design

### Who does what

| Role | Can |
|---|---|
| AI Agent administrator (`ai_agent.group_manager`) | Hermes connections and models; create departments' profiles and assistant users; set assistant users' groups (with Settings); every agent |
| Department manager (Employees manager of the department) and department AI admin | Their department's agents and profile: instructions, persona, skills, enabled tools, model (from enabled models), audience; activate and pause |
| AI Agent user | Chat with agents they are in the audience of; see their own conversations |

Department AI admins are chosen per department by an administrator (a field on the department), like the
department managers of ADR 0009. Department changes take effect without approval; each change is recorded
(revision and chatter).

### AI assistant users

- `res.users` with `ai_assistant_department_id` (or company-wide), created by an administrator from the department
  ("Create AI assistant"). Internal user, no password, cannot log in (credential check refuses it), no email
  invitation, hidden from user pickers and login screens. Archiving a person never affects it.
- Its groups are its role: an administrator gives it the read rights the department's agents need, for example
  Employees officer for HR.
- Every action records "HR Assistant on behalf of Sara" or "on behalf of workflow Overdue reminders".

### Hermes profiles

- `ai.agent.profile`: engine, slug, department (or company-wide, or a single agent), persona (Hermes `soul`),
  default model, skills, enabled toolsets, MCP servers, state (in sync / needs sync / failed), last sync.
- Synced through the Hermes management API: `POST /api/profiles`, `PATCH/DELETE /api/profiles/{name}`,
  `PUT /api/profiles/{name}/soul`, `PUT /api/profiles/{name}/model`, skills (`/api/skills`, `/api/skills/toggle`),
  toolsets (`/api/tools/toolsets/{name}`), MCP servers (`/api/mcp/servers`). Verified on Hermes v0.21.3.
- One Hermes gateway serves every profile (`gateway.multiplex_profiles`), each profile with its own API key,
  stored with the existing encrypted credential storage.
- Agent instructions and the model per agent are still sent with each run, so several agents share one profile.
- The Odoo MCP server is always configured on every profile; other toolsets (web search, ...) are chosen per
  profile. Terminal, file and browser-control toolsets are never offered.

### Odoo tools (MCP server in Odoo)

- An MCP endpoint in Odoo (`/ai_agent/mcp`). Each run gets a short-lived token bound to the run: agent, assistant
  user, and the person or workflow it acts for. The token expires when the run ends.
- Phase 3 tools, read-only: `search_records(model, text or filter, fields, limit)`, `read_record(model, id,
  fields)`, `record_activities(model, id)`, `record_messages(model, id)`.
- Phase 4 tools, prepare-only: `draft_note`, `draft_activity`, `propose_change(model, id, values)`; each creates
  an Approval Center request (adapter, ADR 0008). The approved change runs as the assistant user after checking
  that the person who asked may still change the record.
- Permission check on every call: the model and fields are in the agent's scope (set by its department), the
  assistant user may read them, and in a chat the person may read them too (record rules and field groups for
  both). Results are trimmed to the run's context budget.
- Knowledge sources stay as today (excerpts sent with the question); the fixed pre-sent business data (8 models,
  fixed filter) is replaced by the tools, which look up what the question needs.

### Ask agent step in Workflows

- New step kind in `workflow_ai`: agent, a question with record fields filled in, and what to do with the answer:
  write it to a field, post it as a note, or choose the Yes or No path (the answer must be yes or no).
- Runs as the department's assistant user; the workflow waits for the answer like a Wait step; a failed or
  stopped run follows the step's error setting.

### Tools and services view

- On each profile: its toolsets, MCP servers (Odoo always on) and Hermes scheduled jobs (`/api/cron/jobs`), with
  enable and disable. Scheduled jobs created in Odoo run through Workflows instead (non-scope for Hermes cron
  creation).

## Phase 0 findings (Hermes v0.21.3, source; 2026-11-07)

- **Profiles from Odoo: yes.** The management API creates, renames and deletes profiles (`POST /api/profiles`,
  `PATCH`/`DELETE /api/profiles/{name}`), writes the persona (`PUT .../soul`), description and model; skills,
  toolsets, MCP servers and `.env` values take a `profile` parameter, so one management connection manages every
  profile.
- **One gateway for all profiles: yes.** With `gateway.multiplex_profiles: true` on the default profile, its API
  server serves `/p/<profile>/v1/...`, each profile authenticated by its own `API_SERVER_KEY` (set through
  `PUT /api/env?profile=...`). Odoo's connection check today refuses URLs with a path: it must accept the
  `/p/<profile>` prefix. Secondary profiles must not run their own gateway.
- **Per-run identity at an MCP server: no.** The MCP identity header is static or per profile, MCP connections are
  pooled per profile, and the run API accepts only `input`, `instructions`, `model`, `session_id`,
  `previous_response_id`, `conversation_history` and `request_id`. Design: a random one-run key in the run's
  instructions, required by every Odoo tool, accepted only with the same profile's MCP token while the run is in
  progress (ADR 0012).
- **Odoo MCP server registration:** `POST /api/mcp/servers?profile=...` with `url` and a bearer token (kept in the
  profile's `.env`).
- **Live check (2026-11-07): passed**, on a throwaway Hermes home (`HERMES_HOME` in a scratch folder, gateway on
  127.0.0.1:8653, dashboard on 9129; the owner's Hermes was not touched), Hermes v0.21.3:
  - `POST /api/profiles` created profile `hr`; `PUT /api/profiles/hr/soul` wrote its persona;
    `PUT /api/env?profile=hr` set its own `API_SERVER_KEY`. Management calls authenticate with the dashboard
    session token as a bearer token.
  - With `gateway.multiplex_profiles: true`, no gateway restart was needed: the hr key reached `/p/hr/v1/...` (200)
    and was refused on `/v1/...` (401); the default key was refused on `/p/hr/...` (401); no key: 401.
  - `POST /p/hr/v1/runs` was accepted and ran in the hr profile (it failed only because the throwaway home has no
    model provider); reading the run through another profile's path: 401.
  - `POST /api/mcp/servers?profile=hr` with `auth: header` and a bearer token added the server to hr's config only;
    the token is stored in hr's `.env` and referenced as `${MCP_ODOO_API_KEY}`.
  - Side effect to handle: creating a profile also writes a shell shortcut `~/.local/bin/<name>` on the Hermes host
    (removed after the test). Odoo-created profiles should use names that cannot collide with commands (prefix,
    for example `odoo-hr`).
  - Running Hermes here needed Python 3.12 with the venv's packages (`/mnt/agent/hermes-agent/venv` points to the
    system Python 3.14, which lacks them); the same problem affects the local `hermes` command.

## Phases

0. ADR; spike on the local Hermes: multiplexed gateway with two profiles and keys, profile create and soul write,
   and whether Hermes passes a per-run token to an MCP server (if not: one token per profile plus the run id
   Odoo sends, checked against open runs). Mocks for every new screen.
1. Department AI roles and assistant users (no Hermes change). **Done 2026-11-07** (`ai_agent` 20.0.1.7.0):
   assistant users, department AI admins, department-owned agents, department AI tab; company assistant and the
   profile section of the tab come with phase 2.
2. Profiles managed from Odoo; existing agents move to the company profile; the hand-made `odoo-internal`
   profile becomes the company profile.
3. Odoo MCP read tools with the permission rules; pre-sent business data removed.
4. Prepare-only tools through Approval Center.
5. Ask agent step in Workflows.
6. Tools and services view.

## Verification

- Python tests per phase: assistant user cannot log in; department admin can change only their department's
  agents; permission intersection (a record the person cannot read is never returned; a field in the person's
  hidden groups is never returned); workflow runs use the assistant user; proposals create approval requests and
  nothing is written before approval; profile sync against a recorded Hermes API.
- Live check on the local Hermes for phases 2 to 5.

## Risks and open points

- Hermes management API is the dashboard API: not versioned. Pin the tested Hermes version and check it on
  connection.
- Per-run identity at the MCP server depends on what Hermes forwards (phase 0 spike).
- Department profiles share Hermes sessions; memory stays off.
- Assistant users with broad groups are powerful: the permission intersection protects chats, but workflow runs
  use the assistant's full rights. Administrators must give them only what the department's agents need.
