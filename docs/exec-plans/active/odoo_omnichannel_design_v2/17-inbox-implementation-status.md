# Supervised inbox implementation — 2026-10-06

Addon: `addons/omni_channel`, version `20.0.1.2.0`. Extends the [outbound worker](16-worker-implementation-status.md) with provider-neutral verified intake, private-text conversations and supervised replies. This is a foundation increment, not a live-provider or complete P2 release.

## Implemented

- Endpoint-bound POST controller at `/omni/inbound/<route_key>`, using Odoo's database-bound HTTP transaction. Query selectors are rejected. Adapter verification sees original bytes before decoding; invalid requests retain no content. Core bounds bodies to 1 MiB, parse depth to 16, parsed nodes to 10,000, normalized events to 100, keys to 256 characters and message text to 65,536 characters. Verified intake is limited to 600 events per endpoint per minute in persistent database state.
- Explicit processing policies with immutable activated configuration, pause/resume, actor/time evidence, retention settings and legal holds. Read-only endpoint verification and a release-ready installed adapter are required for activation. Endpoint ownership remains immutable; intake and normalization recheck policy/version.
- Restricted durable events with non-null account/event uniqueness, canonical-content fingerprints, collision quarantine and no contact/business-record creation during acknowledgement. Duplicate HTTP delivery is acknowledged without another effect. Odoo commits before returning success; persistence failures return 503 and roll back partial storage.
- Private identities, conversations, text messages and revision history. Out-of-order edits preserve the newest revision; conflicting revisions are quarantined. Normalization atomically creates its records and clears pending payloads. Unsupported groups/media are metadata only; receipts remain unresolved metadata awaiting provider-specific reconciliation.
- Five-attempt normalization retry budget and sanitized dead letters. Manager replay preserves the event key and original ownership/policy. Expired, blocked and collision events cannot be restored through replay.
- Team-specific and company-wide blocklists. Confirmation records the actor, time, identity, scope and reason; unblock records a separate actor/time and never grants consent. Company-wide confirmation requires system administration. Checks occur before normal objects and again before outbound claims. New blocks clear pending content, subject to legal hold on preexisting evidence.
- Policy-bound retention: pending payload default seven days, message/revision bodies 90 days, blocked evidence 30 days. A legal hold suspends disposal. Successful processing clears pending content early. Expired event tombstones prevent duplicate delivery from resurrecting erased content.
- Explicit linking to an existing accessible contact through a confirmation dialog, without automatic matching, creation or merging. Contact display/open actions recheck contact permissions and company boundaries; linking does not expand access.
- Native Inbox, blocked-identity, policy and intake-event views. Operators can take ownership, wait/close/reopen, inspect revisions and prepare a reply. A reply is tied to the exact conversation/endpoint/thread in its frozen payload and requires the original connection's healthy selected sender, consent and separate approval. Copying a reply preserves its conversation restrictions.
- Global company/team restrictions and guarded server-owned fields. Portal/public users have no inbox ORM access. Message content is plain text and is never passed to AI, chatter notifications or arbitrary business actions.

Concurrency and scope decisions are recorded in [ADR 0002](../../../design-decisions/0002-omnichannel-supervised-inbox.md). In particular, the shared company row-version guard prevents stale PostgreSQL snapshots from missing suppression changes. Sender write/unlink guards were also corrected to check every channel in a recordset rather than only the last one.

## Verification

Tests run only in `omni_build_20261006` with `/tmp/omni-build-data`; existing production databases are unchanged. All inbound/provider inputs are mocks. No real endpoint, provider registration, external message or automation policy was activated.

```sh
PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_build_20261006 --data-dir=/tmp/omni-build-data \
  -u omni_channel --test-enable --test-tags=/omni_channel --stop-after-init \
  --http-port=8077 --max-cron-threads=0 --logfile=/tmp/omni-inbox-final-test.log
```

Full-suite result: **77 tests passed, zero failures/errors**, including three headless Chrome scenarios and independent PostgreSQL concurrency/crash checks. After the final private-thread mismatch/privacy refinement, the 22-test inbox model suite passed again using `--test-tags=/omni_channel:TestOmniInbox --no-http` and log `/tmp/omni-inbox-final-model-test.log`. Together these runs cover **78 distinct tests**. Static parsing is supplemented by actual Odoo module upgrade/view validation.

`/tmp/omni-test-deps/bin/ruff check addons/omni_channel` passed, `git diff --check` passed, and `/home/moshkou/workspace/odoo/odoo-venv/bin/python addons/approval_center/tests/test_approval_center_static.py` passed all 11 tests.

The browser screenshot was visually inspected at `/tmp/odoo_tests/omni_build_20261006/screenshots/omni_inbox_20261006_122637_476179_test_native_inbox_renders_untrusted_text_and_assignment.png`. It shows the native inbox, assignment, existing-contact action, unavailable-reply explanation and escaped untrusted message text.

New evidence maps to:

| Area | Tests |
|---|---|
| T13 verified ingress, size/auth/database selectors, rollback before acknowledgement | `TestOmniInbox.test_invalid_auth_body_and_size_never_persist`; `TestOmniInboxHTTP.test_webhook_authentication_bounds_and_duplicates`; `test_persistence_failure_does_not_acknowledge_or_leave_partial_event` |
| T14 dedup/collision and independent SQL uniqueness | `test_verified_intake_is_durable_then_normalizes_once_without_contacts`; `test_changed_event_key_is_quarantined_without_rewriting_history`; `TestOmniInboxTransactions.test_simultaneous_duplicate_ingress_has_one_effect` |
| T15/T21 disabled/policy/ownership checks | `test_policy_pause_and_ownership_change_hold_queued_intake`; `test_wrong_endpoint_and_unsupported_types_never_make_conversations`; `test_policy_and_endpoint_defaults_fail_closed_without_adapter` |
| T16/T19 suppression and stale-snapshot race | `test_block_precedes_identity_creation_and_unblock_does_not_replay`; `test_block_after_intake_purges_pending_body`; `test_company_block_requires_system_role_and_scope_isolated`; `test_expired_block_does_not_suppress`; `TestOmniInboxTransactions.test_stale_worker_snapshot_cannot_miss_committed_block` |
| T17 retention and hold | `test_retention_purges_bodies_and_revisions_with_legal_hold`; `test_hold_preserves_preexisting_evidence_without_allowing_blocked_processing`; `test_expired_pending_content_retains_only_a_nonreplayable_tombstone` |
| T18 text edits only | `test_edits_out_of_order_preserve_revisions_without_regression` |
| T04/T05/T06 reply continuity and permissions | `test_assignment_reply_and_blocked_reply_use_governed_command`; `test_reply_copy_preserves_context_and_incompatible_sender_is_blocked`; `test_scope_and_rpc_guards`; `test_read_search_export_and_company_boundaries`; `test_existing_contact_link_is_explicit_and_does_not_expand_company_access`; `test_private_thread_identity_mismatch_creates_no_new_identity` |
| Recovery and bounded intake | `test_failure_rolls_back_normalization_and_dead_letter_replays_once`; `test_rate_limit_is_persistent_and_no_payload_saved_on_rejection` |
| T26 browser | `TestOmniInboxHTTP.test_native_inbox_renders_untrusted_text_and_assignment` verifies escaped script text, reply hold explanation and persisted ownership; screenshot visually inspected |

The duplicate race uses a real uncommitted ingress record and a competing SQL insert to assert the database unique constraint; sequential HTTP tests separately verify duplicate acknowledgement. The stale-worker test starts a genuine older snapshot, commits a block in another session and asserts serialization before retrying. Fixture-only role checks are bypassed for transaction setup; role enforcement is tested through model and HTTP suites. Committed fixtures are explicitly removed.

## Operational and remaining gates

All new cron jobs and endpoints ship disabled. No production adapter is registered, so activation fails closed. The route identifier is not an authentication secret; an adapter must independently authenticate each request. Production needs host/dbfilter binding, HTTPS, proxy abuse limits, secret provisioning and bounded adapter I/O. No arbitrary provider URL or file fetch exists here.

This slice supports private text only. Receipt-to-command reconciliation, group participants, attachments, full identity/metadata erasure, restore/backup retention, throughput certification, live bus refresh and delegated assignment remain pending. No automatic service-response consent is inferred from an incoming message. Outbound activation still requires its separate live-release gates.

Next: isolated Telegram Bot API private-text adapter, credential resolution, genuine authentication/normalization fixtures, sender-activation preflight outside locks, explicit operational activation and an authorized sandbox certification. Do not describe the catalog entry as live support until those gates pass.
