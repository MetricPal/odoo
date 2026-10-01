# Odoo 20 verification: auth_magic_link

Verified against the Odoo 20 Community source in this repository before adapting the Odoo 19 `auth_email_link` reference.

## Verified APIs and conventions

- `ir.config_parameter` uses typed `get_str`, `get_int`, `set_str`, and `set_int` methods (`odoo/addons/base/models/ir_config_parameter.py`). The Odoo 19 `get_param`/`set_param` calls are not valid.
- `res.config.settings` persists `config_parameter` fields with the typed setters (`odoo/addons/base/models/res_config.py`).
- Authentication credentials flow through `res.users.authenticate()` and `_check_credentials()`, returning `uid`, `auth_method`, and `mfa` (`odoo/addons/base/models/res_users.py`).
- HTTP session authentication requires a `login` key before finalizing the session (`odoo/http/session.py`).
- The `website` module republishes `/web/login` with `website=True` and
  `auth="public"`, which activates its website-specific inheritance of
  `web.login_layout` (`addons/website/controllers/main.py` and
  `addons/website/views/website_templates.xml`). A later controller must restore
  `website=False` and the core `auth="none"` behavior. Because primary QWeb view
  inheritance still resolves the Website extension, a dedicated copy of the
  small core login wrapper is required to isolate the authentication page.
- Odoo 20 access CSV files target `ir.access` and use `model_id`, `group_id/id`, `operation`, and `domain` (`addons/*/security/ir.access.csv`).
- SQL constraints use `models.Constraint`.
- OAuth readiness is represented by an enabled `auth.oauth.provider` linked through `res.users.oauth_provider_id` with a non-empty `oauth_uid` (`addons/auth_oauth`).
- Active outbound servers are `ir.mail_server` records with `active=True` (`odoo/addons/base/models/ir_mail_server.py`).

## Adaptation decisions

- Keep `auth_magic_link` as the module boundary instead of copying the Odoo 19 module wholesale.
- Support Password, Magic Link, Both, and OAuth-only modes.
- Fall back effectively to Password if a configured passwordless mode becomes unsafe, preventing administrator lockout.
- Validate settings before saving a passwordless mode.
- Keep raw tokens out of the database and consume them with an atomic SQL update.
- Preserve Odoo's normal authentication and MFA pipeline.
- Keep `/web/login` outside the website rendering context, even when Website is
  installed; retain the Website dependency so this route override loads after
  Website's own override.
- Neutralize Website's shared `web.login_layout` replacement so reset, signup,
  TOTP, and other authentication screens call `web.frontend_layout` directly
  with their header and footer disabled. Signup and reset retain Odoo's native
  public frontend request initialization, which the frontend layout requires.
- Add model/security tests and HTTP rendering/request tests.

## Branding mail rendering

- Odoo 20 renders the password-reset QWeb body first, then wraps it with
  `mail.mail_notification_layout` in
  `auth_signup.models.res_users._action_reset_password()`.
- Every SMTP-bound email is finalized through `mail.mail._prepare_outgoing_list()`;
  this is the common hook used to append the branding footer to notifications,
  alerts, template emails, and optional mass mailings. `mailing_id` identifies
  mass-mailing output whose editor-selected background color must be preserved.
- `mail.mail.record_company_id` provides the business-record company for the
  footer, with `env.company` as the fallback. Company city and country are
  address fields delegated by `res.company`. The footer uses every configured
  address component and deliberately leaves the address empty when the company
  record has no address rather than publishing invented business information.
- `odoo.tools.mail.append_content_to_html()` inserts footer HTML before a
  document's closing body tag and also supports HTML fragments.
- Odoo's standard `mail.mail_notification_layout` content wrapper is naturally
  left-aligned but has no explicit alignment attribute. Branding marks that
  wrapper before rendering; the outgoing hook uses the marker (or an explicit
  left-aligned body) to align the footer box left and otherwise defaults it to
  center.
- Mass-mail test messages carry `mail.mail.mailing_id`. Branding preserves the
  first outer campaign background color on the footer's full-width wrapper and
  places the alignment attribute directly on its inner table for compatibility
  with email clients that do not center tables from a parent cell's text style.
- Periodic Digest has no model marker on its generated `mail.mail`, and its
  encapsulating layout is stored as escaped template text. Branding therefore
  marks the rendered main digest table and applies the body canvas color in the
  outgoing hook. Its original unsubscribe link remains hidden for token
  preservation and is rendered beside Privacy in the shared footer. The same
  footer uses mass mailing's standard
  `/unsubscribe_from_list` placeholder, which Odoo personalizes per recipient.
- Odoo's Periodic Digest card is rendered as two adjacent `.global_layout`
  tables: `#header` and the KPI/content table. Branding rounds the header's top
  corners and the content table's bottom corners with the same 12px radius as
  the shared footer, retaining one continuous digest card.
- The Website application provides `/privacy` as the standard privacy-policy
  path. The footer turns it into an absolute URL with the outgoing record's
  base URL.
- Odoo 20 Binary/Image fields expose `BinaryValue` objects; raw image bytes
  are read from `.content`. XML file data uses `type="bytes"`.
- The backend web client receives authenticated-user metadata from
  `ir.http.session_info()`. Branding extends that payload with the current
  user's email for the profile header instead of treating the login as email.

## Branding navigation

- Odoo 20 exposes root applications through `menu.getApps()` and navigates with
  `menu.selectMenu()` (`addons/web/static/src/webclient/menus/menu_service.js`).
- Apps and Settings are the permission-filtered roots
  `base.menu_management` and `base.menu_administration`. Branding removes those
  XML IDs from the launcher input and derives its user-menu entries from the
  same app list, preserving native access rules and navigation behavior.
- User-menu items are ordered through the `user_menuitems` registry sequence;
  the moved pair uses a registry separator above Apps and the existing visual
  separator before Log out.

## Unavailable referenced documentation

`AGENTS.md` references project documents under `docs/` that were not present when this verification was performed. This note records the source-level verification required by the available local research skill.
