# Gap resolution register

Status refers to specification completeness, not implemented behavior. Each decision is normative in the linked contract and requires the listed test evidence.

| Gap | Resolution | Contract | Evidence |
|---|---|---|---|
| contradictory cardinality | one company/purpose/type channel; 0..N endpoints/senders; 0..1 selected | 02, 03 | T01-T04 |
| module versus record ownership | stable purpose catalog; business links separate | 03, 04 | T01, T05 |
| company and endpoint uniqueness | required company; globally exclusive physical canonical endpoint | 02, 03, 11 | T02, T05 |
| replying through wrong identity | strict selected sender; incompatible reply blocked, new outreach explicit | 02, 05, 09 | T04 |
| approval payload/sender drift | immutable version/hash, policy snapshot, generation pinning | 04, 08 | T06-T08 |
| existing approval integration | reuse and harden Omni-linked Approval Center requests | 04 | T06, T12, T25 |
| block before scope resolution | ownership resolution before scoped block, no business side effects | 02, 08 | T15-T16 |
| retry and crash ambiguity | durable outbox, leases/fencing, unknown outcome, no blind retry | 08 | T08-T12 |
| identity/contact ambiguity | identity namespace separate from participant membership; manual partner link | 03 | T02, T05, T20 |
| reassignment/historical access | versioned controlled transfer; initially prohibit activated reassignment | 08 | T21 |
| raw payload versus blocked privacy | discard blocked body; restricted bounded inbox retention | 08, 11 | T13, T16-T17 |
| state-machine conflation | independent approval/command/delivery/event lifecycles | 08 | T07-T12, T18 |
| secret/webhook/attachment security | opaque references, verified ingress, safe media and no public blobs | 11 | T05, T13, T22 |
| business/AI side effects from inbound | explicitly activated narrow policy; separate grants for business/AI | 02, 08, 11 | T15, T24 |
| broad capabilities falsely implying support | catalog distinct from installed verified operation grants | 01, 06, 13 | T04, T20 |
| Community feature assumptions | source-verified mail/SMS; social_media is configuration only | 04, 13 | T25 |
| UI hides approval/sender limitations | explicit Submit for approval, sender identity and unknown outcome UX | 09 | T26 |
| consent/bulk ambiguity | immutable recipient scope plus live suppression; bulk later | 08, 11 | T19, T23 |
| unbounded delivery roadmap | phased core/mock/private-text slice, optional adapters | 07, 12 | release gates |
| operations/restore missing | pause, reconcile, restore disabled, measured capacity targets | 11 | T27 |

## Remaining prerequisites, with owner and closure evidence

| Item | Owner | Needed for | Closure evidence |
|---|---|---|---|
| actual sandbox bot and authorized recipient | deployment administrator | P3 live tests | identity/health and approved test result |
| secret provisioning, HTTPS ingress/database routing | deployment administrator | live ingestion | verification request and redacted configuration check |
| ingestion/retention/service-response policies and approvers | business/security owner | live activation | explicit activation audit and assigned approvers |
| infrastructure capacity, backups and alert destination | operations owner | production | T27 benchmark and restore report |
| company/purpose team membership | company administrator | real data access | access matrix and T05 fixtures matched to deployment |
| future-provider API version/scopes/review | adapter implementer + account owner | each future adapter | source dossier, fixtures and live sandbox gate |

These prerequisites do not block P0-P2 coding. Do not silently activate a default live policy or fabricate evidence to close them. No unresolved foundational architecture question remains for the scoped first implementation; discoveries from code/tests must still update the plan.
