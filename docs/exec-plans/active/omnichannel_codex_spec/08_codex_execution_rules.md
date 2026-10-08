# 08 — Codex Execution Rules

This document is an execution contract.

## MUST

- Implement the architecture exactly as defined in this folder.
- Refactor the current UI where it conflicts with these rules.
- Preserve valid backend functionality while correcting presentation and information architecture.
- Use Odoo 20 Community conventions.
- Keep the design extensible for future channels/providers.
- Use progressive disclosure for technical data.
- Make statuses and runtime ownership explicit.
- Enforce business rules in backend constraints/services, not only in the UI.

## MUST NOT

- Do not ask for product-level clarification when the requirement is defined here.
- Do not present multiple alternative architectures.
- Do not preserve a poor existing UI merely because it already exists.
- Do not create "Advanced Configuration".
- Do not make Telegram the canonical implementation.
- Do not expose database internals in primary UX.
- Do not duplicate native Email/SMS management.
- Do not mix setup wizard UI with the normal Overview after onboarding.
- Do not connect LLMs to Hermes Agent as part of this work.
- Do not redesign Hermes Agent in this module.

## IMPORTANT

The existing implementation is not authoritative. This specification is authoritative.

If an existing screen conflicts with this specification, modify the screen.

If an existing menu conflicts with this specification, modify the navigation.

If an existing model is useful but its fields are too technical for primary UX, keep the model and redesign its views.

## VALIDATION

After implementation, verify:
- empty state
- generic channel wizard
- first channel activation
- second channel activation
- multiple outbound senders
- sender health failure
- sender switch
- multiple inbound endpoints
- inbound purpose ownership
- blocklisted inbound event
- monitoring/technical details
- Overview after setup
- Configuration navigation
- Technical administration placement
