# Project Changelog

Record major architectural, product and implementation changes here.

Format:
- date
- change
- reason
- affected areas
- migration/compatibility notes

## 2026-10-07

- Fixed catalog/channel readiness remaining available after adapter uninstall in
  the same process. Provider registration now identifies its owning addon and UI
  readiness checks the current database's installed modules. Core 20.0.1.4.1;
  Telegram 20.0.1.0.1. Shared factories are retained for other databases.
- Rehearsed native Telegram and core removal on disposable synthetic databases.
  Adapter removal preserves core evidence; core removal deletes Omni tables.
  Documented destructive teardown limits and verified unrelated approval drafts.

- Added loopback SMTP integration tests for native alert/recovery delivery and
  explicit delivery rejection. Validated recipient/MIME content, delivery status
  and no duplicate queueing after failure. No runtime or live mail setup changed.

- Added shared, disabled-by-default operations email policies per channel.
  System administrators explicitly authorize recipients and monitoring; changed
  aggregate counters and recovery use Odoo's existing mail queue. Scope and
  recipient access are rechecked, unchanged states are quiet, native delivery
  failures remain inspectable, and neutralized restores disable alerts.
  Upgrade `omni_channel` to `20.0.1.4.0`; no live policy is enabled by this upgrade.

- Omni-Channel derives webhook URLs from backend `web.base.url`, using
  `channels.[configured hostname]` and the endpoint route key. Removed the draft
  manual server/domain settings and preview. Local-only backends yield no public
  URL. No infrastructure or provider registration changes are executed.
- Existing Odoo outgoing mail remains the transport for future operations
  alerts; the SMTP account does not identify an alert recipient.

## 2026-10-04

- Change: Reworked `approval_center` from an action-first prototype into an
  Approval Types workflow with field rules, seeded default types, dashboard
  request cards, multiple approvers, duplicate-approver protection,
  employee-manager approval, minimum approval defaulting to 1, and hidden
  technical action plumbing.
- Change: Added horizontal Approval Type field-rule controls and an Archived
  filter in the Approval Types configuration list.
- Change: Filtered already-selected approvers out of the approver dropdown on
  Approval Type and Approval Request forms.
- Change: Approval Request forms now materialize Approval Type configuration:
  configured approvers load when the request opens or the category changes, and
  request fields appear only when the type marks them required or optional.
- Fix: Approval Request Period now renders From and To on one aligned row so
  later fields such as Location do not slip into the period block.
- Fix: Approval Request users can now create/update/delete approver lines on
  their own requests, while Approval Type approver configuration remains
  administrator-controlled. Approvers can update their own approver line status.
- Fix: Submitted approval requests now notify approvers through Odoo's
  notification engine in addition to scheduling review activities.
- Fix: Review activities now set a visible Summary so the My Activities list
  shows the approval request prompt instead of an empty summary column.
- Fix: Restored Approval Center review activity completion with
  `activity_feedback()` on approve/refuse/cancel.
- Fix: User deletion with Calendar installed now removes the deleted user's
  `calendar.user` memberships with `sudo()`, because Odoo Calendar's
  `res.users.unlink()` cleanup was failing for users allowed to delete
  `res.users` but not allowed to delete another user's calendar membership.
- Reason: Match the researched Odoo Approvals user model and keep target
  model/action details out of the requester experience.
- Affected areas: `approval_center` models, views, access rules, tests, and Odoo
  verification references.
- Migration/compatibility notes: New module was still in foundation stage.
  Databases that installed the earlier prototype should upgrade before real use.

- Change: Added the `approval_center` module foundation with approval requests,
  policies, audit logs, security groups, backend views, module identity, and a
  custom icon.
- Reason: Start the real Approval Center module using the researched Odoo
  approval model: project policy and audit first, execution through app-specific
  Odoo actions.
- Affected areas: `approval_center`, approval governance docs, Odoo verification
  references.
- Migration/compatibility notes: New module only. Full database-backed install
  validation still requires PostgreSQL availability.

- Change: Updated authentication branding states, shared auth footer, public
  auth `v` query alias, AI Home Favorites star visibility, and AI Home card
  hover/focus styling.
- Reason: Match requested UX for reset-password, magic-link confirmation,
  authentication footer/privacy visibility, and AI Home interaction states.
- Affected areas: `branding`, `auth_magic_link` inherited auth shell,
  `auth_signup` inherited reset-password page, `web` inherited login page, and
  `ai_home` dashboard UI.
- Migration/compatibility notes: Uses Odoo 20 QWeb inheritance and the existing
  standalone auth shell. Full database-backed module validation still requires
  PostgreSQL availability.
