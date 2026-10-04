# 2026-10-04 Auth Branding and AI Home UX Updates

## Objective

Implement the explicitly requested TODO items for authentication branding and
AI Home UX while preserving Odoo 20 Community mechanisms and recording durable
project references.

## Scope

- Authentication page copy and layout in the branding module.
- Shared authentication footer with company name, `© 2026 .`, and Privacy link.
- Public auth URL handling for `v` as an alias for `db`.
- AI Home Favorites star visibility.
- AI Home card hover/focus visual treatment.
- Regression tests and project reference updates for the changed behavior.

## Non-Scope

- No rewrite of Odoo core authentication flows.
- No changes to authorization, record rules, approval policy, or real business
  data execution.
- No new AI automation behavior.
- No replacement of Website's `/privacy` content.

## Affected Modules

- `branding`
- `ai_home`
- `auth_magic_link` through inherited templates/routes only
- `auth_signup` through inherited reset-password templates only
- `web` through inherited login templates only

## Dependencies

- Odoo 20 Community source in this repository.
- Website application standard `/privacy` route/page.
- `auth_magic_link.standalone_login_layout` as the active standalone auth shell.
- Project rules in `AGENTS.md`, `docs/PLANS.md`, `docs/RESEARCH.md`,
  `docs/ODOO20.md`, `docs/DESIGN.md`, and `docs/QUALITY.md`.

## Design Decisions

- Keep global authentication chrome in the shared standalone authentication
  layout instead of duplicating footer markup on each auth page.
- Keep page-specific titles/subtitles in page bodies, not in the shared shell.
- Treat reset password as three distinct UX states:
  - email-entry: `Reset your password`
  - token/password-entry: `Set your password`
  - sent-instructions: `Check your email`
- Use normal flex layout for the bottom auth footer, not absolute positioning,
  so the footer stays in document flow on short screens.
- Keep magic-link sent-instructions focused on logo, title, subtitle/message,
  and `Back to Login`; hide login form, OAuth divider, OAuth providers, and
  user-switch content in that state.
- Keep AI Home favorite-star actions visible only when Favorites is expanded.

## Implementation Steps

- Updated `addons/branding/views/webclient_templates.xml`:
  - auth footer replacement
  - bottom-of-viewport flex layout
  - reset-password state-specific headings
  - magic-link sent-instructions state cleanup
  - centered `Back to Login`
- Updated `addons/branding/controllers/main.py`:
  - accept `v` as alias for `db`
  - redirect public auth URLs away from visible `db=`
- Updated `addons/ai_home/static/src/dashboard/dashboard.xml`:
  - show favorite star only while Favorites is expanded
- Updated `addons/ai_home/static/src/dashboard/dashboard.scss`:
  - replace hover/focus border emphasis with accent background
- Updated regression tests:
  - `addons/branding/tests/test_branding.py`
  - `addons/ai_home/tests/test_dashboard_templates.py`
  - `addons/ai_home/static/tests/dashboard.test.js`
- Updated durable references:
  - `docs/DESIGN.md`
  - `docs/references/odoo20-verification.md`

## Verification Steps

- Ran `python addons/ai_home/tests/test_dashboard_templates.py`.
  - Result: passed.
- Ran Python compile check for `addons/branding/tests/test_branding.py`.
  - Result: passed.
- Parsed `addons/branding/views/webclient_templates.xml`.
  - Result: passed.
- Attempted broader Odoo database testing.
  - Result: not completed because PostgreSQL on localhost:5432 was unavailable.
- JavaScript/HOOT browser tests.
  - Result: not run because no local runner was identified during the task.

## Risks

- Full Odoo module/database tests were not completed, so final QWeb inheritance
  behavior still needs validation in a running Odoo database during upgrade.
- Browser rendering was checked manually by screenshot feedback, not automated
  visual tests.
- The fixed `© 2026 .` footer text is product-requested; revisit if the product
  later requires a dynamic year.

## Rollback Strategy

- Revert the branding QWeb/controller changes to restore the previous auth page
  rendering and public auth query handling.
- Revert the AI Home dashboard XML/SCSS/test changes to restore previous
  favorite-star visibility and hover styling.
- Remove or update the related documentation entries if the behavior is rolled
  back.

## Completion Status

Completed with documented limitations. Remaining recommended validation is a
full Odoo module upgrade/test run once PostgreSQL is available.
