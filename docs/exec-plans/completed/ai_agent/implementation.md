# AI Agent implementation plan

Status: **Active**, 2026-10-12. User approved development as `ai_agent`, using
Hermes as the engine and Odoo Enterprise AI as the business/UX reference, with
our stronger governance controls. Keep transport simple: direct HTTPS APIs.

## Delivery gates

1. Internal assistant: configuration, approved instructions, scoped sources,
   requester-authorized data, conversations, durable runs and immutable evidence.
   Implemented; 39 isolated tests pass, including two real Chrome UI tests.
2. Hermes management: verified version contract, model/provider controls,
   tool/service discovery and reviewed profile configuration synchronization.
   Read-only discovery and live health/tool/memory checks implemented; managed
   configuration mutations and live inference acceptance remain open.
3. Governed actions: curated MCP tools, action-specific policies, frozen Approval
   Center requests, revalidation, idempotent execution and continuation. Open.
4. Enterprise-style contextual experience: streaming chat, attachments, source
   indexing, Discuss/chatter/context entry points and default prompts. Open.
5. Automation and channels: existing Workflows and Omnichannel adapters, explicit
   schedule activation, audience/consent boundaries and deployment gates. Open.

No milestone closure implies production activation or later feature completion.

## Initial boundary

New addon only. No changes to `omni_channel`, `omni_telegram`, business execution
methods, existing approval behavior, or deployed application databases. The
first release denies Hermes callable tools and shared memory. It permits only
explicit inference requests, supplied permitted context, explanation and drafts.
Use real Odoo 20 `ir.access`, `BinaryValue`, native views and cron claims.

## Verification

See [module guide](../../../../addons/ai_agent/README.md). Tests cover explicit
identity/audience, company boundaries, source isolation, data-field allowlists,
configuration review, history immutability, request quotas, uncertain submission,
cancellation claims, transport restrictions and real manager/staff browser flows.
Local Hermes was located read-only: dashboard on 127.0.0.1:9119, version
0.21.3, source commit 6cd2502. Its run API is not listening and the existing
profile has shared memory enabled. The user explicitly approved a separate odoo-internal profile. Its API is
running on 127.0.0.1:8643 and management on 127.0.0.1:9120. The actual Odoo
adapter reports Ready, zero enabled callable toolsets and shared memory disabled.
The engine record is stored only in the isolated test database. A live inference
test, persistent service deployment and installation in the existing Odoo service
remain outstanding.

Verification on 2026-10-12: `/tmp/ai-agent-verified-tests.log` reports **39 tests, zero failures/errors**. Initial installation and subsequent upgrades pass. Final clean-install log: `/tmp/ai-agent-clean-install.log`. Static Python/XML parsing and `git diff --check` pass. No live Hermes request or external message was sent.

## Form enhancement — 2026-10-12

All native forms refined: explicit labels/placeholders, Local/Remote connection
setup, masked write-only credentials, advanced management settings, automatic
source preparation, native Odoo source permissions, full conversation answers,
and role-sensitive evidence. No deployed database was upgraded.

`/tmp/ai-agent-forms-v3.log`: 50 tests, zero failures/errors, including five
Chrome test methods and credential/access checks. Screenshots visually reviewed.
The broader app roadmap remains open.

Final conversation spacing verification: `/tmp/ai-agent-forms-final.log`, one
browser test method passed after the final layout correction.

Management setup now has an explicit same-URL/API-key checkbox. Shared mode
uses the run URL and credential even when separate settings were saved before;
switching back restores those settings. Changing the checkbox invalidates
readiness. Local profile connections continue to use their separate API surfaces.

Checkbox verification: `/tmp/ai-agent-management-checkbox.log`, 51 tests,
zero failures/errors; real browser visibility and backend credential switching
verified.

URL validation now reports the specific rejection: missing/malformed address,
insecure remote protocol, credentials in the URL, a non-base path/query/fragment,
or missing deployment endpoint approval. Existing allowlist and IP/TLS safety
boundaries remain enforced; submitted URL secrets are not echoed in errors.

Validation verification: `/tmp/ai-agent-url-errors.log`, 52 tests passed with
zero failures/errors, including 11 specific URL error cases.

## Provider/model picker delivery — 2026-10-13

Implemented a native manager-only dialog under Hermes engines and paused/draft
agent configuration. Unified provider/model search, current default markers,
connected/setup-required status, empty catalog guidance and source-sensitive
model selection follow the inspected Hermes inventory contract. Credentials and
unrecognized metadata are excluded from the dialog payload. Agent selection
re-fetches the catalog before saving; unauthenticated providers and absent models
are rejected. Existing activation/selected-company checks remain enforced.

Authentication and engine-main-model changes use the connected profile's native
Hermes `/models` dashboard. No OAuth/token exchange, generic environment writes,
remote model mutation, automatic sign-in or inferred authorization is introduced
in Odoo. Provider-specific setup stays under Hermes's management permissions;
Odoo managers need their own authorized Hermes dashboard login. A browser on
another machine needs a reachable reviewed management URL, not its own loopback.

Verification: `/tmp/ai-agent-picker-final.log` reports 56 tests with zero failures
or errors. After final dialog layout correction,
`/tmp/ai-agent-picker-dialog-final.log` passed the engine-button/modal/search
check, with screenshot reviewed. `/tmp/ai-agent-picker-save-browser.log` passed
a separate full agent selection/save browser test. These use synthetic catalog
data and never mutate a real Hermes provider or submit inference. Python/XML
parsing and `git diff --check` passed. The running application database still
requires an approved addon upgrade and debugger restart.

## Persistent engine model workflow — 2026-10-13

Supersedes the temporary popup workflow above. Management is now in main
connection setup, beside the run API. Providers & models is a persistent engine
tab with selectable model checkboxes and a stored Enabled models list. Multiple
models can be enabled without changing Hermes's main model. Agent configuration
uses a native dropdown restricted to its engine's enabled entries.

The registry has a unique engine/provider/model identity, native company rules,
manager-only mutations, immutable identity and creator/editor audit fields.
Enabling rechecks discovery/authentication and serializes concurrent clicks;
disabling a selected model blocks further agent use. An override's provider
authentication is rechecked before inference. Legacy overrides must be enabled
and reselected. Hermes still owns provider secrets and its native setup flow.

Final verification: `/tmp/ai-agent-enabled-models-final.log`, **60 tests, zero
failures/errors**. Includes real Chrome multi-model persistence and native agent
dropdown/save/navigation flows, runtime auth revocation, duplicate enable and
disabled-model/staff access rejection. Native screenshots reviewed;
`git diff --check` passed. No live provider change or inference was submitted.
Version 20.0.1.3.0 requires an application upgrade and restart.

Saved enabled-model rows also have a confirmed Remove action, so managers can
disable entries no longer present in discovery. Final targeted verification:
`/tmp/ai-agent-model-removal-final.log`, two tests passed.

2026-10-14: corrected local provider setup handoff. `hermes serve` on 9120
is headless; the browser link now uses dashboard 9119 with the explicit
`odoo-internal` profile. The API management endpoint remains 9120.
Targeted method checks passed for the local profile URL, manager-guard
invocation and unchanged remote endpoint validation. An Odoo regression test
was added; the full database suite was not rerun for this URL-only correction.

2026-10-14 UI refinement: Model Settings is now a native URL hyperlink.
Add model replaces Refresh catalog and opens the searchable provider/model
popup. Checkbox changes retain manager/company/fresh-authentication checks;
closing reloads the engine Enabled models list. Full clean-install suite in
`/tmp/ai-agent-add-model-popup.log`: 63 tests, zero failures/errors.

2026-10-14 status refinement: replaced the success banner with an outline status
pill before the statusbar, using the checked-out HR EmployeeUserStatus visual
pattern without adding an HR dependency. Simplified local setup, saved-key, API
purpose, model selection and diagnostics messages. Failed checks retain their
specific error. Connection edits clear stale verification.
`/tmp/ai-agent-status-pill.log`: 62 tests passed, including header geometry and
backend stale-message regression. Screenshot reviewed. Version 20.0.1.3.2.

2026-10-14: removed framework branding from visible instructions, source access
labels/help, provider setup copy and connection errors. Permission enforcement
and technical identifiers remain unchanged. XML/Python parsing, visible-string
checks and `git diff --check` passed; no behavioral changes or full-suite rerun.

2026-10-14: per user direction, removed the verification pill and engine
statusbar. Only failed-check warnings remain visible; internal readiness and
last-check tracking are unchanged. Removed the unused badge assets.
