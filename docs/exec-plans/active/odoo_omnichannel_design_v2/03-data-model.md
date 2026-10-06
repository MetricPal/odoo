# Data model — implementation contract

All operational records have required `company_id`, server timestamps in UTC, and indexed state/ownership keys. Global read-only catalogs are the exception. Relational company checks supplement global access restrictions. Durable IDs/keys are non-null strings; provider numbers are preserved as strings. JSON metadata is bounded, schema-versioned and contains no credentials.

## Models

| Model | Essential fields and relations | Constraints / lifecycle |
|---|---|---|
| omni.purpose | code, name, active, permitted_group_ids, integration_key | unique code; stable catalog; purpose membership AND company access required |
| omni.channel.type | code, name, icon, active | twelve extensible catalog entries; not evidence of implementation |
| omni.provider | code, channel_type_id, adapter_key, supported_api_version, readiness | installed registry only; no arbitrary Python import path |
| omni.account | company_id, provider_id, external_account_key, canonical_namespace, credential_reference, credential_version, config_version, health | unique company/provider/external account; verified namespace; reauthentication of same identity retains identity |
| omni.channel | company_id, purpose_id, channel_type_id, active, generation, inbound_policy_id | unique company/purpose/type; generation increments on sender switch |
| omni.outbound.sender | channel_id, account_id, sender_key, is_selected, active, config_version, health_status, health_checked_at | unique channel/sender key; partial unique selected channel; cross-channel physical sender claim unique |
| omni.inbound.endpoint | channel_id, account_id, endpoint_key, canonical_namespace, ownership_version, state | global physical key unique type/namespace/endpoint; draft/verified/enabled/disabled; preserve archived ownership |
| omni.inbound.policy | company_id, channel_id, version, allowed_operations, activated_by/at, active | immutable activated version; ingestion only by default |
| omni.identity | company_id, channel_type_id, canonical_namespace, external_identity_key, identity_type, partner_id | unique company/type/namespace/key; partner link optional and checked; display handles are not identifiers |
| omni.conversation | channel_id, endpoint_id, ownership_version, namespace, external_thread_key, state, assigned_user_id, last_message_at | unique company/endpoint/ownership_version/thread; new/open/waiting/closed |
| omni.participant | conversation_id, identity_id, role, joined_at, left_at | membership, not replacement for identity; unique conversation/identity |
| omni.message | conversation_id, event_id, command_id, external_message_key, message_kind, direction, body, occurred_at, revision | provider key scoped to account/endpoint/thread; inbound duplicate unique key; preserve edits as revisions |
| omni.attachment | company_id, message_id or command_id, attachment_id, checksum, scan_state, size, mime_type | wrapper around private ir.attachment; no duplicate blob engine; quarantine/clean/rejected |
| omni.capability | code, name, operation_schema_version | global code catalog |
| omni.capability.grant | account_id, sender_id or endpoint_id, capability_id, constraints, evidence, checked_at, expires_at, version | scope explicit; unknown/expired is unavailable |
| omni.webhook.event | account_id, endpoint_id, ownership_version, event_key, event_kind, schema_version, state, payload_ref, payload_hash, attempts, next_attempt_at | unique account/event_key; received/processing/processed/blocked/unresolved/retry/dead |
| omni.command | uuid, channel_id, sender_id, channel_generation, operation, canonical_payload, payload_hash, revision, requester_id, approval_request_id, policy_version, expires_at, state | immutable after submission; unique company/client_request_key and UUID; mismatch on reused key rejected |
| omni.delivery | command_id, recipient_key, provider_message_key, state, accepted_at, delivered_at, read_at | unique command/recipient; pending/accepted/delivered/read/failed/unknown; no fake receipts |
| omni.attempt | command_id, number, lease_token, started_at, ended_at, outcome, sanitized_error, provider_request_key | unique command/number; append-only; dispatch evidence survives retry |
| omni.blocked.identity | company_id, purpose_id optional, channel_type_id, namespace, external_identity_key, scope, reason, source, expires_at, actor_id | purpose or company scope; separate partial unique indexes for null-purpose company scope and non-null-purpose scope |
| omni.moderation.decision | event_id, model/provider/version, policy_version, classification, risk, confidence, recommendation, approval_request_id | append-only; cannot directly mutate blocklist |
| omni.audit.event | company_id, purpose_id, actor_id, technical_actor_id, event_type, resource_key, correlation_id, before_hash, after_hash, outcome | append-only application permissions; no cascading deletion from operational parent |
| omni.endpoint.assignment | endpoint_id, old/new channel, old/new ownership_version, actor, timestamp, reason | append-only ownership history |

Before first live sending, add the minimal `omni.consent` evidence model: company, purpose, identity, operation, status, evidence reference, captured_by/at, expires_at and withdrawal time. Service-response eligibility may reference the verified inbound event and activated response policy; this is not promotional consent. Enforce unique current scope and retain append-only evidence history. Full consent-management UI arrives before bulk.

Later-phase models: `omni.bulk.job` and immutable `omni.bulk.recipient` snapshots; `omni.social.post` draft/preview linked to commands; `omni.template` provider template ID/language/version/status; `omni.business.link` explicit permitted model/record relation and access-checked display.

Queue fields on `omni.command`: next_attempt_at, attempt_count, lease_token, lease_expires_at, dispatch_authorized_at, held_reason, last_safe_error, cancel_requested_at and originating policy/evidence references. These are server-managed operational fields excluded from the approved content hash. Index the due-queue lookup. Parent command state changes never rewrite frozen payload or prior attempts.

## Identity and thread rules

Telegram first slice: namespace is verified bot ID; endpoint key is bot ID; identity key is sender user ID; conversation key is chat ID. Limit to private text updates with a sender identity. Message ID is scoped by bot and chat. Bot username is display-only. Edited messages are distinct events updating a revision, not new conversation entries. Unsupported update types are recorded as ignored metadata, not misclassified as customer text.

Adapters supply canonical keys for other providers before enablement. Do not infer user identity from a display name, match by an unverified email, or merge contacts automatically. Group threads use membership records. Public/social actions may not have a person sender and need their own event schema.

## Business references

No unrestricted model/method names from clients. Registered bridge code declares allowed business models, allowed link operations and required access. Links never expand access: reading the conversation does not grant access to the applicant/employee/lead. Chatter mirrors sanitized summaries only when authorized; it is not a second transport.

## Deletion and indexes

Archive configuration in use; restrict deletion of referenced channels/accounts/identities. Retention jobs remove payloads and attachment blobs according to policy while preserving minimal pseudonymous command/audit evidence where permitted. Legal holds suspend disposal. Index due jobs by state/next_attempt_at, conversations by company/channel/last_message_at, events by account/key, and block lookups by company/type/namespace/key/scope. Use Odoo 20 `models.Constraint` and `models.UniqueIndex`; test real database enforcement.
