---
name: web-ux
description: Design and review this project's ERP web UX, including Odoo form sheets, cards, kanban boards, lists, and contextual approval surfaces.
---

# Web UX Skill

Design the ERP web experience around work, approvals and contextual intelligence.

Use:
- top bar
- anchored floating app launcher
- AI Workstream
- Approval Center
- contextual AI actions

Avoid a permanent left navigation drawer as the default navigation pattern for this product.

## Odoo view principles

Apply the user's screenshot-based view conventions in
[docs/DESIGN.md](../../../docs/DESIGN.md#odoo-view-principles) when designing or
reviewing Odoo views. These are the project defaults:

- Form: design the record sheet, the left white box in the reference. Keep the
  surrounding Odoo controls and chatter in their native roles.
- Cards: design the individual card's content and hierarchy within Odoo's grid.
- Kanban board: retain Odoo's grouped stage/column structure and design the cards
  within it; distinguish this from an ungrouped card grid.
- List: show the essential columns initially and include the remaining relevant,
  permitted business columns as `optional="hide"`, available in the native
  column selector. Hidden by default is a display choice, not access control.
- List with KPIs: keep the summary strip above the native list and apply the same
  column rules.

Verify view syntax and extension points against the checked-out Odoo 20 source
before implementation. During UI verification, check sheet/card boundaries,
board grouping, and optional-column toggling with an appropriate user role.
