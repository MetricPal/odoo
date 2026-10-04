# Approval Center Foundation

## Objective

Create the first real `Approval Center` module for this AI-native Odoo 20
project. The module provides a reusable approval object, policy layer, audit
trail, and action-based execution pattern that can later integrate with
app-specific Odoo approvals such as Purchase, Expenses, and Time Off.

## Scope

- New Odoo Community addon: `approval_center`.
- App identity: name, description, icon, menus.
- Approval request model.
- Approval policy model.
- Approval audit model.
- Security groups and access controls.
- Backend list/form/search views.
- Action-based execution through configured public Odoo action methods.
- Documentation and reference updates.
- Basic static/syntax/XML checks.
- Follow-up UX and permission fixes discovered during browser testing.

## Non-Scope

- No automatic execution of real business approvals during installation.
- No AI automation activation.
- No direct integration yet with Purchase/Expenses/Time Off pending queues.
- No external communication, payment, posting, confirming, or other live
  business execution without user action.

## Affected Modules

- New: `approval_center`
- Documentation: `docs/`

## Dependencies

- `base`
- `mail`
- Odoo 20 Community source in this repository.
- Project approval rules in `docs/APPROVALS.md`.
- Odoo approval research in `docs/references/odoo20-verification.md`.

## Design Decisions

- Use `Approval Center` as the module name.
- Store reusable approval requests separately from target business records.
- Execute approved work through configured Odoo action methods, not direct final
  state writes.
- Always write audit records for policy decisions, approvals, refusals,
  execution attempts, success, blocked execution, and failures.
- Keep target linkage generic using model name and record ID so integrations can
  be added incrementally.
- Keep security conservative: internal users can create/read their own requests;
  approvers and managers can review; only managers configure policies.

## Implementation Steps

- Created module manifest and custom SVG icon.
- Created `approval.center.policy`, `approval.center.request`,
  `approval.center.approver`, and `approval.center.audit`.
- Reworked the first action-first prototype into an Approval Types flow:
  types define field rules, multiple approvers, manager approval, approver
  sequence, and minimum approval defaulting to 1.
- Added default Approval Types with icons: Business Trip, Borrow Items, General
  Approval, Contract Approval, Payment Application, Car Rental Application, Job
  Referral Award, and Procurement.
- Restricted Approval Type create/edit to Configuration by making the dashboard
  kanban non-create and non-open.
- Added duplicate-approver protection for Approval Types and Approval Requests.
- Filtered already-selected approvers out of the approver dropdown on both
  Approval Type and Approval Request forms.
- Added Approval Type driven request fields and validation. Document, Contact,
  Date, Period, Items, Quantity, Amount, Reference, Payment, and Location are
  shown on requests only when the selected Approval Type marks them required or
  optional, and required fields are checked before submit.
- Approval Request forms now preload default approvers from the selected
  Approval Type both from dashboard defaults and from category changes.
- Fixed Approval Request Period layout so From and To render together in one
  aligned row.
- Fixed `approval.center.approver` access rules so request owners can manage
  approver lines on their own requests, normal users can still read Approval
  Type approver defaults, and approvers can write their own approval status.
- Submitted approval requests now call Odoo's `message_notify()` for active
  approver partners after scheduling review activities, so approvers receive
  an inbox notification or email according to their Odoo notification setting
  and outgoing mail configuration.
- Review activities now set both `summary` and `note`, making the request visible
  in the My Activities Summary column.
- Hid target model/action fields from the normal request form. They remain only
  as technical execution plumbing for future module integrations.
- Added security groups: User, Approver, Administrator.
- Added access rules for requests, categories, approver lines, and audit rows.
- Added list/form/search views, actions, menus, and review activity type.
- Added Approval Type configuration UX fixes:
  - horizontal Required/Optional/None radio controls;
  - Archived search filter for inactive Approval Types;
  - fixed column widths so Approval Type list headers are fully visible;
  - smaller list icons and compact dashboard cards;
  - scoped list-handle alignment styles.
- Restored post-submit review activity completion on approve/refuse/cancel with
  Odoo's `activity_feedback()` API.
- Fixed the actual Calendar access failure observed while deleting a user:
  `addons/calendar/models/res_users.py` deletes the removed user's
  `calendar.user` memberships before deleting the `res.users` record. That
  cleanup now runs with `sudo()` because the acting user may have permission to
  delete the user but not permission to delete another user's Calendar
  membership record.
- Added database-free static tests.
- Restored request search Group By filters using the core Odoo search-view
  pattern: plain `<group>` with filters carrying `domain="[]"` and
  `context="{'group_by': ...}"`.
- Updated references and changelog.

## Verification Steps

- `python addons/approval_center/tests/test_approval_center_static.py`
  - Result: passed, 4 tests.
- `python -m py_compile` for module Python files and static test.
  - Result: passed.
- XML parse for security XML, views XML, and icon SVG.
  - Result: passed.
- Focused static tests after restoring the Odoo-style search Group By filters.
  - Result: passed, 4 tests.
- Focused static tests after Approval Type defaults and duplicate-approver
  checks.
  - Result: passed, 6 tests.
- Focused static tests after Approval Type UI fixes, approver dropdown
  filtering, restored activity feedback, and Calendar user-deletion cleanup.
  - Result: passed, 10 tests.
- Focused static tests after Approval Type driven request fields and default
  approver loading.
  - Result: passed, 11 tests.
- XML parse after follow-up Approval Center changes.
  - Result: passed.
- Python compile after follow-up Approval Center changes.
  - Result: passed.
- Odoo CLI smoke check with `/usr/bin/python3 odoo-bin --help`.
  - Result: blocked by missing local dependency `passlib`.

## Risks

- Full Odoo module installation, ORM behavior, access rule evaluation, and QWeb
  view loading still need validation in a configured Odoo Python environment and
  PostgreSQL database.
- Generic action execution must stay conservative to avoid bypassing target
  module business rules.
- Calendar user deletion changes a core Odoo addon override. It is intentionally
  narrow, but still needs database-backed validation with a non-admin internal
  user that has user-management rights.

## Rollback Strategy

- Remove the `approval_center` addon.
- Remove related documentation entries from `docs/references/odoo20-verification.md`
  and `docs/CHANGELOG.md`.
- No migration is required until the module has been installed in a database.

## Completion Status

Completed as a foundation module with follow-up UX and permission fixes
recorded. Next recommended step is database-backed module installation and
integration tests, especially around Calendar-installed environments and
review activity lifecycle behavior.
