# Odoo 20 Community Implementation Contract

## Target

Odoo 20 Community Edition is the implementation target.

## Version discipline

Before writing Odoo-specific code:

1. Verify the actual Odoo 20 Community source tree.
2. Verify official Odoo 20 documentation/API behavior.
3. Verify model names, fields, ORM behavior, views, assets, OWL/web client APIs, security mechanisms and module manifests against Odoo 20.
4. Record important version findings in `docs/references/odoo20-verification.md`.
5. Do not copy Odoo 18/19 implementation patterns merely because they are familiar.

## Compatibility rule

Older Odoo versions may be consulted only for historical context or migration analysis. They are not implementation authority for Odoo 20.

## Community Edition

Do not assume Enterprise-only capabilities exist in Community Edition. Verify every dependency.

## Extension strategy

Prefer:
- supported extension points
- inheritance
- existing Odoo services
- standard ORM/security mechanisms
- minimal monkey-patching

Avoid unnecessary forks of Odoo core.

## Required verification record

Every major Odoo integration should record:
- source/documentation checked
- exact version/commit if available
- API/model/view assumptions
- known compatibility risks
- test evidence
