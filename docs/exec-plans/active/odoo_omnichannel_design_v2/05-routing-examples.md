# Routing and failure examples

## Several inbound endpoints, one selected sender

Company A / Marketing / WhatsApp has inbound numbers A and B; outbound configurations A and B; selected sender A. Both endpoints route to Marketing. A message to B is visible, but an in-thread reply is blocked unless adapter validation proves selected sender A is compatible. The system never secretly sends as B. Explicit new outreach from A is a separate approved command when allowed.

## Company isolation

Company A Sales and Company B Sales have different channels. A physical bot/number cannot be claimed by both. Adding a second credential record for the same external endpoint does not bypass uniqueness. A user selecting both companies still needs the relevant purpose membership and record access.

## Blocklist order

Verified bot event -> resolve bot endpoint to Company A/Recruitment -> normalize external identity -> check company-wide block then Recruitment block -> persist allowed event -> asynchronous conversation handling. A Recruitment-only block does not affect Sales. Company-wide means all purposes in Company A, never all tenants or companies.

## Unknown and reassigned endpoints

An authenticated event for an unconfigured endpoint enters restricted quarantine, with no contact/lead/notification creation. Reassignment disables intake, drains or explicitly quarantines pending old-version events, holds outgoing work, then increments ownership version with human confirmation. Old conversations remain with their original purpose. Reactivation admits only new-version events; ambiguous late events remain quarantined.

## Approval and sender switch

Command C approved for sender A at channel generation 5. Admin switches to B, generation 6. C becomes held, not rewritten. User clones C with B and submits a new request. Switching back to A does not resurrect generation-5 commands.

## Uncertain provider outcome

Provider accepts C, worker loses response. Mark C `unknown`; do not retry a non-idempotent send. Reconcile from provider evidence if available. An operator can mark a verified success or explicitly create a replacement command acknowledging possible duplication; replacement requires fresh approval. Never label uncertainty as a definite failure.

## Email/SMS

Native Odoo engines remain authoritative. Future unified activity bridges correlate native IDs and statuses without scheduling a second send.
