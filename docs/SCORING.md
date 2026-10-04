# Module Completion Scoring Matrix

Use this matrix to rate each completed module or substantial module milestone.
Score out of 100, then apply gates.

## Gates

A module cannot be rated complete if any gate fails.

- Approval/security gate: state-changing behavior respects `docs/APPROVALS.md`
  and `docs/SECURITY.md`.
- Odoo 20 gate: Odoo-specific behavior is verified against Odoo 20 Community
  source/API and recorded when meaningful.
- Evidence gate: completion is backed by tests, checks, screenshots, logs, or a
  clear documented reason why a check could not run.
- Documentation gate: changed behavior, architecture, risks, and references are
  updated in the relevant docs.

## Score Bands

- 95-100: Excellent. Complete, verified, documented, low residual risk.
- 85-94: Good. Complete with minor known limitations.
- 70-84: Acceptable. Works, but has meaningful gaps to address.
- 50-69: Weak. Partial implementation or insufficient verification.
- 0-49: Not acceptable. Core outcome missing, unsafe, or unverified.

## Matrix

| Area | Points | What earns full credit |
| --- | ---: | --- |
| Requirements fit | 15 | User goal, acceptance criteria, and non-scope are understood and implemented without unrelated changes. |
| Odoo 20 correctness | 15 | Uses verified Odoo 20 Community APIs, views, ORM/security patterns, assets, and extension points. |
| Security and approvals | 15 | Respects user type, groups, record rules, company boundaries, public/portal visibility, and human approval boundaries. |
| UX/product fit | 10 | Matches product direction, design docs, accessibility, and expected user workflow. |
| Implementation quality | 15 | Small, maintainable changes using existing project patterns with clear module boundaries. |
| Tests and verification | 15 | Appropriate unit/integration/Odoo/UI checks run, with failures or unavailable checks documented. |
| Documentation and traceability | 10 | Updates references, plans, changelog/design decisions where needed, with what/when/how/why preserved. |
| Reporting quality | 5 | Final report is concise and includes changes, tests, limitations, and follow-up work. |

## Rating Template

Use this at module completion.

```text
Module:
Date:
Score:
Gate status:
- Approval/security:
- Odoo 20:
- Evidence:
- Documentation:

Breakdown:
- Requirements fit: /15
- Odoo 20 correctness: /15
- Security and approvals: /15
- UX/product fit: /10
- Implementation quality: /15
- Tests and verification: /15
- Documentation and traceability: /10
- Reporting quality: /5

Evidence:
- Plan:
- References:
- Tests/checks:
- Screenshots/logs:

Known limitations:

Decision:
- Complete / Complete with follow-up / Not complete
```
