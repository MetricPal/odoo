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
