# AI Agent

Supervised Hermes assistants for Odoo 20 Community. Technical module: `ai_agent`.
Odoo owns identity, data selection, permission enforcement and run evidence;
Hermes supplies inference through its HTTP run API. No NATS or custom broker.

## Delivered first increment

- Native Agents cards/list/forms, Skills, Sources, Conversations, Activity and
  Configuration menus; manager and staff experiences have separate permissions.
- Explicit internal-user audience, selected-company restrictions, bounded reads
  as the requester, stored scalar-field allowlists and JSON record filters.
- Reviewed instructions, source preparation for PDF/UTF-8 text, native Odoo source access
  rules and bounded lexical excerpt selection with source names/revisions.
- Explicit inference request, durable submission claim, unique session/request
  identifiers, polling, stop requests, append-only evidence and usage attribution.
- HTTPS or numeric-loopback HTTP host/port allowlist, validated/pinned IP, TLS hostname verification,
  bounded responses, sanitized errors, no redirects or automatic POST retries.
- Dedicated tool-free and memory-free Hermes profile readiness checks, provider/
  model overrides and read-only engine model/tool/capability discovery.
- Exact-color transparent SVG app icon based on the supplied reference. The
  image-generated PNG is retained as an alternative, not the exact-color source.

## Setup

1. Provision a dedicated Hermes profile. Disable every agent-callable toolset.
   Set `memory.memory_enabled: false`, `memory.user_profile_enabled: false`, and
   disable external memory providers. Start/restart its gateway after applying
   configuration. Do not use this profile for other applications or users' CLI
   sessions. The host administrator remains a trusted execution boundary.
2. Expose its run API and authenticated management API behind HTTPS, or numeric
   loopback HTTP when Odoo and Hermes run on the same host. These are
   distinct Hermes surfaces and may have different addresses/credentials. The
   management API must describe this exact profile; omitted profile scope must
   not accidentally refer to another profile. Provision separate per-profile
   origins for this increment; multiplexed profile prefixes are not supported.
3. Set `AI_AGENT_ENDPOINTS=hermes.example.com:443,management.example.com:443`
   on the Odoo process. Only deployment-approved origins may be contacted;
   HTTP is accepted only for `127.0.0.1` or `::1` and is pinned to loopback.
   Private addresses are permitted over HTTPS for explicitly provisioned endpoints,
   while link-local, unspecified and multicast addresses are denied.
4. Choose **Local Hermes** for the approved profile on this host; **Connect**
   imports its private deployment credentials without asking users for variable
   names. For **Remote Hermes**, enter its HTTPS URL and masked API key. In Management connection, select **Management uses the same URL and API key**
   to reuse the run connection; clear it to enter separate management details.
   The approved local profile uses separate management credentials automatically. Saved keys never read back;
   encrypted files in the Odoo data directory hold them, bound to the database,
   engine, company, purpose and endpoint. Legacy environment references still work.
   Back up `ai_agent_credentials` securely with the database; all Odoo workers
   require access to the same private storage. Host administrators are trusted.
5. Install `ai_agent`, grant AI Agent / User or Manager, add an engine and choose
   **Check connection**. Read-only live acceptance was verified against the local Hermes installation;
   an actual model inference test is still outstanding.
6. Create an agent, choose allowed users, skills, sources and optional data
   scopes. Sources prepare automatically after saving text or a supported file; approve skills. **Activate** confirms the audience,
   data disclosure and request limits. **Chat → Send** authorizes one inference
   request. It authorizes no record change, message or publication.

The worker is installed active but has no work until an explicit user request
queues a run. It polls at one-minute cron cadence, with bounded batches. Inference exceeding
15 minutes requests cancellation. Daily request quotas use UTC calendar days. Refresh
Conversation/Activity to see updated results. Pause blocks new admission and
requests cooperative cancellation; it cannot retract already submitted context,
undo remote actions or guarantee that accepted inference stops incurring cost.

## Safety and recovery

The model has no business execution tools in this increment. This is enforced by
Hermes tool discovery, not an instruction alone. Sources, skills and field/domain
settings influence inference but never grant execution permissions. Fresh
requester/company/configuration checks precede each submission and accepting
results. Configuration changes require renewed activation. Managers supervise
run evidence in their selected companies; staff see their own conversations.

Claims commit before remote submission. Unknown acceptance is **Needs
reconciliation** and retains a concurrency slot. No automatic resubmission
occurs, even when Hermes supports idempotency keys. With a returned remote ID,
**Check remote outcome** performs a read-only reconciliation. Without an ID,
inspect Hermes using the request key; no guessed success or retry is offered.
Stopping is shown separately from confirmed terminal status. Stop POSTs also
have one committed claim and are not repeated automatically.

No credentials or raw remote errors enter run evidence. Approved source/record
content is retained in the manager-only request payload; authorized managers
can inspect it. Evidence retention is currently indefinite and normal RPC
cannot edit/delete it. Define a reviewed retention policy before production.

## Explicit remaining scope

This is the first internal assistant increment, not Enterprise feature parity.
Not implemented yet: in-place streaming chat, prior-turn context, contextual
systray/Discuss/chatter entry points, conversation attachments, semantic/vector
indexing, website URLs and Documents/Knowledge bridges, writable Odoo MCP tools,
frozen action approvals, customer channels, engine configuration/model/service
mutations, external MCP services, runtime skills sync, schedules/workflow/event
bindings, financial budgets, retention jobs and deployment upgrade migrations.
These capabilities must remain unavailable until their enforcement and tests
exist. A source marked Ready has prepared text; it does not claim an embedding
index. Source-only prompting is guidance, not a guarantee against unsupported
model claims; evaluate grounded answers and require human review.

## Test

On an isolated database, with Chrome and websocket-client for browser tests:

```sh
PYTHONPATH=/tmp/ai-agent-test-deps .venv/bin/python odoo-bin \
  -d ai_agent_test --db_host=/tmp/ai-agent-socket --db_port=55439 \
  --db_user=moshkou --addons-path=addons -u ai_agent --without-demo \
  --test-enable --test-tags=/ai_agent --stop-after-init --http-port=8089 \
  --max-cron-threads=0 --data-dir=/tmp/ai-agent-data
```

API tests use synthetic responses and provisioned dummy credentials. They send
no model requests or external messages. Browser tests exercise real Odoo views.

## Verification evidence (2026-10-12)

`/tmp/ai-agent-forms-v3.log`: **50 tests, zero failures/errors**, including
five real Chrome browser test methods, readable PDF extraction, source/record isolation,
immutable history, transport restrictions and worker recovery. Screenshots were
visually reviewed. Final clean-install evidence is in
`/tmp/ai-agent-clean-install.log`, followed by the final Apps-description
upgrade check in `/tmp/ai-agent-clean-final.log`. Live read-only Hermes readiness was verified separately; no inference was sent.

Icon asset workflow: the built-in image editor was prompted to preserve the
supplied border, AI lettering and three stars, remove the background, and use
`#004692`, `#00bdf6`, `#ffb855` respectively. Its PNG preview has alpha transparency;
the app uses the faithful SVG reconstruction for exact solid palette values.

## Located local Hermes (2026-10-12)

Read-only inspection found the dashboard at `http://127.0.0.1:9119`, reporting
version `0.21.3`, source commit `6cd2502`, under `/mnt/agent/hermes-agent`.
The active home is `/mnt/agent`. Dashboard health/capability paths return HTML;
it is not the run API. No separate API listener was found. Source contains the
required run, discovery and model-option routes. The current profile has memory
and user-profile stores enabled and no explicit disabled toolsets.

A new `odoo-internal` profile is proposed, with run API at
`http://127.0.0.1:8643` and management at `http://127.0.0.1:9120`.
`deployment/local-profile.yaml` is a reviewed configuration draft only.
The user explicitly approved creation/startup. The new profile is running on
these ports and its readiness was verified through the actual Odoo adapter.
The existing profile configuration was not changed; no live inference request
was sent.
The desired model/provider must be provisioned separately, with no reuse of
current messaging sessions, scheduled jobs, memory or channel credentials.

Read-only live adapter result: **Ready**, zero enabled callable toolsets, both
shared memory stores disabled. Verified engine record exists only in the isolated
`ai_agent_test` database. The existing Odoo service on port 8069 has not been
reconfigured, restarted or upgraded. After an approved upgrade, Local Hermes setup imports the approved profile
credentials privately. The Odoo process still requires the approved endpoint
allowlist; keys must never be copied through chat. The two new
Hermes services are detached processes, not systemd units; persistence across
reboot is not configured. Their PIDs are recorded in the new profile directory.

## Form refinement (2026-10-12)

All configuration and working forms use explicit names, useful placeholders,
native sheets and role-sensitive technical details. Conversation cards and request
forms show full question/answer text. Source uploads prepare on save; extracted
content appears only when available, and errors explain unsupported/scanned PDFs.
New sources use native creator access and manager permissions; existing legacy
reader grants remain compatible. Additional group access is configured through
Odoo 20 `ir.access`, scoped by company and checked as the actual requester.
No invented department/company audience selector grants access. Documents and
Knowledge permissions are not bridged in this increment.

Replacing connection credentials or changing endpoints invalidates readiness.
Stored credentials are write-only through normal ORM access, and opaque storage
references are inaccessible to normal users. Private encrypted files can outlive
a rolled-back transaction or replaced key; automatic cleanup is not implemented.

Final conversation spacing verification: `/tmp/ai-agent-forms-final.log`, one
browser test method passed after the final layout correction.

Connection validation reports missing/invalid URLs, insecure remote HTTP,
embedded credentials, paths/query strings, and deployment approval separately.
Errors never display a submitted password, API key, path or query value.

### Local endpoint deployment prerequisite

Load `deployment/odoo-local.env.example` into the Odoo process environment
(preserve any other explicitly approved endpoints). This is not an `odoo.conf`
option. Restart every Odoo worker after changing its environment. Terminal
launchers may prefix their existing command with
`AI_AGENT_ENDPOINTS=127.0.0.1:8643,127.0.0.1:9120`. For systemd, use the service
Environment/EnvironmentFile configuration; for containers, use the container
environment. This approves only the previously reviewed local API surfaces.

## Providers, models and authentication

On each saved Hermes engine, **Providers & models** is a persistent tab with
one search field, providers on the left and model checkboxes on the right.
**Refresh catalog** reads the installed Hermes inventory. Enable multiple
models; they remain visible in the **Enabled models** list below the catalog.
Enabling is idempotent, company-scoped and records native creator/editor history.
Unconfigured providers cannot be enabled. Connection edits must be saved before
model changes. Disabling a selected model blocks further use by its agents.

Agent **Engine & limits → AI model** is a native dropdown filtered to that
connection's enabled models. Leave blank for Hermes's configured default.
Active agents must be paused before changing their model. Legacy provider/model
overrides must be enabled and reselected; arbitrary identifiers are rejected.
The provider/model mapping is derived server-side, checked against the engine,
and authentication is checked again before submitting an override to Hermes.

**Management connection** is part of the main setup, next to the run API.
It supplies the memory safety check and the reviewed profile's setup dashboard.
The shared URL/key checkbox controls whether separate management fields appear;
local endpoints and credentials remain automatic. **Provider setup in Hermes**
opens the browser dashboard; locally this is
`http://127.0.0.1:9119/models?profile=odoo-internal`. Port 9120 runs headless
`hermes serve` and remains the management API, not a browser UI. Hermes owns API-key, OAuth and custom
server authentication and engine-default changes. Odoo never copies provider
secrets or dashboard credentials into browser URLs. The dashboard requires its
own authorized login. Browser loopback addresses refer to the browser machine;
remote users need a reachable, reviewed management endpoint.

Module 20.0.1.3.0 requires an upgrade and restart for schema/views/assets.
No running business database or real Hermes provider was changed by these tests.

Verification: `/tmp/ai-agent-enabled-models-final.log` — **60 tests passed**,
including persistent multi-model enabling and saving an agent's native model
selection in Chrome. Authentication revocation, disabled-model blocking,
idempotency, manager permissions and regression tests passed. Screenshots were
reviewed and `git diff --check` passed.
