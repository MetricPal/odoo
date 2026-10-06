# Telegram sandbox implementation status

Date: 2026-10-06. Base: inbox commit `68c72f776884` (`feat(omni_channel): add verified intake and supervised inbox`). Core version 20.0.1.3.0; optional `omni_telegram` version 20.0.1.0.0.

## Implemented

- Optional trusted Telegram adapter with private-text/edit normalization, shared-secret header authentication, bot identity verification, recipient preflight and one-shot send invocation. No automatic webhook registration or polling.
- Environment secret bundles bound to the exact database, company and bot. Only opaque references enter the database. Fixed-host HTTPS verifies TLS and public DNS addresses, pins the selected numeric address and imposes DNS/socket/total-time/body budgets. No proxy-environment routing, redirects or HTTP retries.
- Deployment networking off by default. A manager must explicitly verify/authorize the sandbox bot, record evidence and list one to ten consenting recipients. Configuration becomes immutable while authorized. Explicit revoke stops new intake and claims and holds unclaimed work; in-flight sends may finish.
- Endpoint processing policy, selected sender, sandbox authorization, verified original conversation, exact recipient consent and distinct per-message approval are separate gates. A channel action explicitly enables sandbox dispatch; all scheduler activation remains separate. Neither installation nor authorization sends a message.
- Successful API replies retain the scoped bot/chat/message key. Ambiguous results remain unknown and cannot automatically resend. API rejection handling allows bounded 429 delay through the existing worker retry contract. No delivered/read claim is made.
- Read-only sender health preflight now occurs before acquiring the company/channel lock; configuration/version/generation are rechecked under lock before publishing the result. Provider sends remain outside ORM transactions via the existing committed claim worker.
- Core immutable dispatch claims and endpoint configurations carry private non-secret adapter scope metadata. Core tests use a separate mock transport catalog entry, so optional real adapter behavior cannot alter mock test semantics.
- Native account configuration and channel activation controls, explicit confirmation, server-side role/scope/default-context guards and readable sandbox limitations. The browser screenshot was reviewed and the configuration paragraph corrected to span the group width.

The [addon runbook](../../../../addons/omni_telegram/README.md) gives the complete activation sequence, secret contract, revocation/rotation procedure and limitations. [ADR 0003](../../../design-decisions/0003-telegram-supervised-sandbox.md) records the boundaries.

## Verification evidence

Only `omni_build_20261006` and `/tmp/omni-build-data` were installed/upgraded. No real Telegram requests, credentials, webhook registration, external messages or existing production database changes were made. Fixtures are synthetic protocol examples, not live recordings. Provider calls are mocked.

Initial targeted install: `-u omni_channel -i omni_telegram --test-tags=/omni_telegram`, log `/tmp/omni-telegram-test.log`: 15 tests passed. Expanded regression initially exposed the old assertion that all catalog adapters were unavailable; this was corrected to verify catalog identities and actual adapter availability. Browser inspection exposed a cramped group paragraph; the view was corrected and rerun.

Final full command:

```sh
PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_build_20261006 --data-dir=/tmp/omni-build-data \
  -u omni_channel,omni_telegram --test-enable --test-tags=/omni_channel,/omni_telegram \
  --stop-after-init --http-port=8077 --max-cron-threads=0 \
  --logfile=/tmp/omni-telegram-final-test.log
```

Result: **96 tests passed, zero failures/errors** (79 core, 17 Telegram), including four Chrome scenarios and existing independent PostgreSQL concurrency/crash/rollback checks. Odoo's additional fixture timing counters are not extra test methods. The only subsequent test change renamed “signed” to “authenticated” to accurately describe shared-secret webhook verification; behavior is unchanged.

Also passed:

- `/tmp/omni-test-deps/bin/ruff check addons/omni_channel addons/omni_telegram`
- `/home/moshkou/workspace/odoo/odoo-venv/bin/python addons/approval_center/tests/test_approval_center_static.py`: 11 tests.
- `git diff --check` and `git diff --cached --check`.
- Actual Odoo module install/upgrade and inherited-view validation, beyond XML parsing.

Visually inspected screenshot: `/tmp/odoo_tests/omni_build_20261006/screenshots/telegram_sandbox_20261006_124611_946584_test_native_account_requires_explicit_confirmation.png`. It shows the scoped account, synthetic recipient/evidence, inactive authorization and explicit confirmation; the browser deliberately does not confirm activation.

| Contract | Evidence |
|---|---|
| Secret isolation and safe errors | `TestTelegramProvider.test_scoped_secrets_reject_cross_database_company_bot_and_redact` |
| Header verification and unauthorized accounts | `test_verification_requires_authorized_account_and_exact_header` |
| Private-text/edit normalization and unsupported scopes | `test_private_text_and_edit_have_stable_scope_and_revision`, `test_groups_media_business_bots_and_unlisted_recipients_are_ignored` |
| Bound preflight, acceptance and no-send/unknown mapping | `test_preflight_and_accepted_result_are_bound_to_bot_and_private_chat`, `test_explicit_rejections_and_bounded_retry_after`, `test_timeout_server_errors_redirects_and_malformed_success_never_retry`, `test_unapproved_or_unbound_payload_never_invokes_send` |
| Network disabled and resource closure/deadline | `test_network_default_off_and_dns_private_addresses_rejected`, `test_transport_uses_fixed_path_deadline_and_closes_resources` |
| Real ORM governance and revocation | All five `TestTelegramSandbox` methods, including approved inbox reply to fenced acceptance and revoke holding queued work |
| HTTP and UI | Both `TestTelegramHTTP` methods: authenticated duplicate POST and native confirmation without activation |
| Health preflight race | `TestOmniFoundation.test_health_preflight_precedes_lock_and_rejects_changed_configuration`; existing stale-selection and concurrent uniqueness tests |

## Remaining release gates and next step

The next step is **authorized live sandbox certification**, not adding another provider. A deployment owner must supply an approved test bot/recipient through secret provisioning, approved HTTPS/database routing and webhook setup, explicit processing/scheduler policies, and sanitized actual-provider evidence. The runbook specifies the actions and expected outcomes; none have been executed against a live bot.

Production still requires infrastructure capacity/timeout measurement, backup/restore-disabled verification, alert routing, operational ownership and the broader release criteria in file 12. Adversarial slow-network behavior is bounded in implementation but has not been measured against a real network service. Multi-database process registration exposes loaded-code availability globally; exact per-database configuration and secret bindings still fail closed. Separate governed deployment processes are recommended.

Groups, media, bulk, business/guest features, delivery/read receipts, business-record automation, full identity erasure and AI processing remain outside this slice. No enterprise certification or universal exactly-once delivery claim is made.
