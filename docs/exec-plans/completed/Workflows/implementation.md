# Workflows implementation and verification

Plan status: **Complete — current scope closed by the user on 2026-10-12.**
Remaining limitations below are preserved for future work.

Implemented in `addons/workflow_center`, 2026-10-09.
Entry point: **App menu → Workflows** (administrators).

App-menu upgrade verified in the isolated `workflows_clean` database: the
existing menu becomes a root app with its icon and client action, and remains
hidden from non-administrators. The targeted regression test passed with zero
failures or errors (`/tmp/workflows-app-menu.log`).

Overview and Run history use native Odoo navbar sections.
The New button uses the native control-panel button slot and `c` hotkey.
Verified the upgraded module with five browser tests (desktop/mobile, New dialog,
builder, run recovery and approval navigation) plus the menu/access regression:
six passed, zero failures/errors in `/tmp/workflows-native-navbar-final.log`.
Desktop and mobile screenshots were inspected. No live database was upgraded.

The My approvals shortcut was subsequently removed at user request. The upgrade
deletes its menu and dedicated window action using Odoo's obsolete XML-data
cleanup. Approval Center remains the place to review requests. Menu/access and
Overview/Run history browser tests both passed (`/tmp/workflows-remove-approvals.log`).

## Delivered

- Home organized around When → If → Do, description entry, example suggestions,
  eleven categorized templates, available-document selection and saved workflows.
- Visual builder with Actions, Logic and Optional Approval groups. New steps go
  after the selected step, including at the end of a path. Yes/No branches are
  drawn separately; disconnected steps and cycles prevent activation.
- Native Odoo configuration for updates, activities, followers, email and code.
  Record creation has typed field mappings for fixed values, compatible source
  fields and links to the source record.
- Record creation/change, stage/status, date, schedule, manual and incoming
  webhook triggers. Activated manual workflows bind to the document Action menu.
- Durable queued runs, waits, conditions, branches, bounded related-record loops,
  optional Approval Center requests and tracked outgoing webhooks.
- Run history with filters, step details, failure messages, retry, skip and stop.
  Uncertain remote outcomes require checking delivery before an explicit retry.
- Previews that do not execute business actions; explicit activation with
  reviewed definition/action fingerprints, actor and timestamp.
- Company scope, chosen execution-user permissions, append-only history and
  workflow-specific approval protections. Approvers and required counts are
  fixed for each request; requester self-review and direct decision mutation are
  denied. Changes to the source document while approval is pending require a
  fresh review.
- Desktop/mobile layouts and native Approval Center navigation.

## Configuration and integration limits

Templates are editable recipes, not ready-to-send policies. They require the
business apps, recipients, email templates, field mappings, conditions and
approval types appropriate to the installation.

No AI provider or workflow chat adapter exists in this repository. Description
text is retained as a draft brief; the UI explicitly says AI generation is not
connected. The WhatsApp example cannot activate until an adapter is provided
or the administrator replaces that step with an available action.

Existing Approval Center screens are reused. The reference images' unsigned
email/chat decision links, generic record locks, delegation and absence routing
are not introduced by this module. The document Action menu is the manual
entry point; existing business buttons are not silently overridden.

Webhook destinations must be explicitly allowlisted by deployment and support
the supplied stable idempotency key. HTTP failures are synthetic-tested, not
live-certified. A successful email action is an Odoo handoff, not a delivery
receipt. See the [module guide](../../../../addons/workflow_center/README.md).

## Verification evidence

All execution used disposable PostgreSQL on localhost port 55432. No live
database was upgraded and no real provider delivery was attempted.

- Clean install: `/tmp/workflows-clean.log`, zero failures/errors.
- Final regression: `/tmp/workflows-release-check.log`, **34 tests, zero
  failures/errors**.
- Subsequent manual Action-menu permission check:
  `/tmp/workflows-manual-access.log`.
- Browser coverage: desktop/mobile home and builder, separate branch paths,
  native record field mappings, failed-run recovery, preview record picker,
  and navigation between Overview and Run history.
- Integration/security coverage: native event and webhook triggers, date
  configuration, scheduled runs, waits, loops, typed record creation, errors
  and recovery, changed configuration, approval ordering/refusal/self-review,
  changed-record invalidation, portal denial and company/user boundaries.
- Synthetic transport checks cover failure status, pinned public addressing,
  host allowlisting, redirect denial and stable delivery keys.
- Ruff (E9/F63/F7/F82/F401/F841), Python/XML parsing and whitespace checks on
  implementation files passed. The supplied specification retains its original
  CRLF line endings.

Command used for final regression:

```sh
PYTHONPATH=/tmp/workflows-deps .venv/bin/python odoo-bin \
  -d workflows_clean --db_host=/tmp --db_port=55432 --db_user=moshkou \
  --addons-path=addons -u workflow_center --without-demo --test-enable \
  --test-tags=/workflow_center --stop-after-init --http-port=8079 \
  --max-cron-threads=0 --data-dir=/tmp/workflows-clean-data \
  --logfile=/tmp/workflows-release-check.log
```

The code is prepared for review. Installation and activation in the real
deployment remain separate from this implementation.
