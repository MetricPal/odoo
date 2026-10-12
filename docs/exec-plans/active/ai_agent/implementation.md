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
