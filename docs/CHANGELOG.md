# Project Changelog

Record major architectural, product and implementation changes here.

Format:
- date
- change
- reason
- affected areas
- migration/compatibility notes

## 2026-10-04

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
