# ADR 0009: Department workflow managers

Date: 2026-10-21. Status: implemented (operate); authoring for departments proposed.

## Context

Workflows were visible to Settings administrators only. The product owner decided
(setup UX review, 2026-10-21) that department admins should manage their
department's workflows. Workflows install Odoo server actions and automation
rules, and authoring needs read access to technical metadata (models, fields,
server actions) that ordinary users do not have.

## Decision

- A workflow may belong to a department (`department_id`).
- New group "Department workflow manager". A member who manages a department in
  Employees (directly or through a parent department) sees that department's
  workflows, steps and run history.
- They can preview, activate and pause a workflow only when it runs as them
  (`Run as` = the manager). It therefore only touches records they can already
  access. Workflows running as anyone else stay read-only for them.
- Activation installs the automation rule or run button with fixed module code.
  After the permission check this runs privileged; no user-supplied code is
  installed.
- Creating and changing workflows (settings, steps, server actions, templates)
  stays with Settings administrators, who set the department and hand over by
  setting `Run as` to the department manager.
- The app opens on Templates for administrators and on My workflows for
  department managers (the root menu has no action of its own).

## Alternatives considered

- Department managers derived from Employees alone, without a group: rejected;
  access is granted explicitly by an administrator.
- Full authoring for department managers now: deferred; it requires granting
  read access to models, fields and server actions, a separate decision.

## Consequences

- Upgrading adds the group with no members; nothing changes until an
  administrator assigns it and a department on the workflows.
- Steps that call server actions can still only be configured by administrators.
