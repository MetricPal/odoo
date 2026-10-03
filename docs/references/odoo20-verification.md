# Odoo 20 verification: auth_magic_link

## AI Home entry navigation

- Owl 3 exports `proxy` for reactive object state and `signal.ref()` for DOM
  references; it does not export Owl 2's `useState` or `useRef`
  (`addons/web/static/lib/owl/owl.js`). AI Home uses a proxy for dashboard
  state and binds `t-ref="this.favoritesRootRef"` to its instance signal, matching
  native navbar references. `useSortable` expects a callable reference
  (`addons/web/static/src/core/utils/sortable.js`). Dashboard HOOT coverage
  checks mounting, reactive updates, and favorite drag and drop.

- Owl 3 initializes template context as `{ this: this.component, __owl__: this }`
  in `ComponentNode` (`addons/web/static/lib/owl/owl.js`), so component members
  must be referenced through `this`, including getters, method calls, state,
  and DOM reference signals. Dashboard loop variables remain local expressions.
  Database-free regression checks cover all dashboard component bindings.

- AI Home loads `views/ai_home_views.xml` so its client action and internal
  root menu exist after installation/upgrade. The `/odoo` router mapping needs
  `ai_home.action_ai_home` to resolve successfully. Native desktop and mobile
  app launchers are preserved; AI Home no longer replaces or hides them.

- Owl 3 component props are declared with the instance hook `useProps`, not
  static `props` or `defaultProps`. Odoo's compatibility layer explicitly
  rejects static declarations (`addons/web/static/src/owl2/owl3_compatibility_layer.js`).
  AI Home uses `useProps({})` for its search shell and `useProps()` for its
  dashboard's unrestricted client-action props, matching the generic action
  component in `addons/web/static/src/webclient/actions/action_plugin.js`.

### Installation and access control

- `odoo/tools/convert.py::convert_csv_import` derives the target model from
  the CSV filename. Odoo 20 defines `ir.access`, not `ir.model.access`, in
  `odoo/addons/base/models/ir_access.py`; use `security/ir.access.csv`.
- Access records use `operation` (`r` for read permission, `crud` for a
  restriction covering all operations) and `domain`. A record without `group_id` is a restriction; a grouped record is a
  permission, even when it has a domain (`ir_access.py::_compute_kind`).
- AI Home's model is `ai.home.item`, with generated model XML ID
  `model_ai_home_item`. Internal users receive read permission subject
  to the existing company and visibility-group domain; portal users receive
  no permission. Access regression tests use Odoo 20's `has_access()` API.
- The website template remains commented out; backend Home action/menu data
  is enabled.

- Branding's navbar logo links to `/odoo` in
  `addons/branding/static/src/xml/navbar.xml`.
- `addons/web/controllers/home.py` authenticates backend requests and redirects
  non-internal users before rendering backend assets. AI Home retains this flow.
- `WebClient.loadRouterState()` loads the router action before falling back to
  the first app (`addons/web/static/src/webclient/webclient.js`).
- AI Home maps an empty `/odoo` or `/odoo/` entry to its action XMLID using the
  existing router patch, with canonical URL `/odoo/home`. Query parameters are
  retained; explicit actions, models and menu selections keep native routing.
- The router initializes before addon patches; synchronous `replaceState`
  refreshes startup state. Regression coverage is in AI Home's navbar HOOT tests.

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
- Direct `mail.mail` creation is still used by several Odoo 20 outbound paths
  in addition to `mail.template` and notification rendering. Because every
  SMTP-bound email is finalized through `mail.mail._prepare_outgoing_list()`,
  branding uses that hook as the final enforcement point: unbranded, non-mass
  mailing HTML is wrapped once in `branding.branding_mail_layout`; already
  branded notification/template/digest bodies are detected by branding markers
  and are not wrapped a second time.
- Email content and footer alignment uses a 656px outer shell with a single
  content cell padded `24px 28px`, matching the footer's single padded cell and
  leaving a 600px usable content area. Periodic Digest keeps
  its native two-table card structure instead of using
  `branding.branding_mail_layout`, but branding now sets the digest card tables
  to the same explicit inline `width="656"`, `width:656px`, 28px horizontal
  padding, and `#eeeeee` borders so email clients do not fall back to Odoo's
  original `.global_layout` `588px`/`#d8dadd` CSS.
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

## AI Home favorites and demo visibility

- Favorites exclude `ai_home.menu_ai_home_root`, `base.menu_management`, and
  `base.menu_administration` using the XML IDs returned by the permission-filtered
  Odoo 20 menu service. Normalization also removes these IDs from previously
  stored favorites. Favorite star buttons remain visible with View all closed.
- Branding excludes the AI Home root from the shared desktop/mobile launcher
  input, while retaining its client action and Home routing. AI Home is not added
  to the user menu; Apps and Settings retain their existing user-menu entries.
- `odoo/modules/loading.py` loads demo files on installation only when demo is
  enabled, and on upgrade only when the module's `demo` flag is already true.
  An ordinary upgrade therefore does not populate a module installed without
  demo. The local `odoo20` database was inspected: AI Home is installed with
  `demo=False` and zero dashboard items in every section.
- Loading AI Home's demo file requires an approved database operation. Keep the
  sample records in the manifest's `demo` list; do not install fictional approval
  or activity records as production data or enable every module's demo records.
  Only AI Home's `demo/ai_home_demo.xml` needs loading, followed by setting that
  module's `demo` flag for future upgrades. The expected sample counts are five
  attention cards, six administrator-only automation cards, and eight recent
  cards. Company, group, and per-user seen restrictions still apply.

## AI Home model rename

- The model is `ai.home.item`, implemented by `AiHomeItem`. RPC calls, security
  references, demo records, and tests use this name.
- Verified Odoo 20's `MigrationManager` in `odoo/modules/migration.py`: a versioned
  `migrations/1.1/pre-*.py` runs before model initialization when upgrading from
  1.0 to 1.1. `ir.module.module.latest_version` stores the database version;
  `installed_version` is computed from the manifest on disk.
- The pre-migration renames `work_dashboard_item` to `ai_home_item`, preserving
  row IDs, and renames the implicit group relation table and its source column.
  Odoo 20 computes implicit many-to-many names from alphabetically sorted model
  table names (`odoo/orm/fields_relational.py`). The explicitly named
  `ai_home_item_seen_user_rel` remains valid and retains seen-user links.
- Model and field metadata, relation targets, model references, and generated
  model/field/selection XML IDs are updated before reflection, preserving access
  record links to the same `ir.model` ID. Upgrades do not enable demo data.

- Rename validation exposed a pre-existing company-rule issue: its internal-user
  group made it an additional CRUD permission. Clearing `group_id` makes it a
  global restriction, enforcing the existing company/group domain while the
  separate internal-user permission remains read-only. Portal users still have
  no model permission. Targeted tests verify these boundaries after upgrade.

- Applied the upgrade to local database `odoo20` with `-u ai_home
  --stop-after-init --no-http --test-enable`, selecting the migration test and six
  model/security tests. Final result: seven database tests, zero failures/errors.
  Three database-free template tests and JavaScript syntax checks also passed.
  The migration fixture verifies row IDs, group and seen-user links, access-model
  links, generated XML IDs, and repeat execution. Odoo 20 validates the callback
  parameter names; the migration uses `migrate(cr, version)`.

## AI Home native icons

- Odoo 20's backend uses `.oi` with `data-icon` ligatures, defined in
  `addons/web/static/src/webclient/icons.scss`. Filled stars use `.oi-filled`,
  matching `views/fields/boolean_favorite/boolean_favorite_field.xml`.
- Dashboard favorites use `data-icon="star"`; section toggles use
  `chevron_forward` as in the native date picker. The attention badge uses `ai_home/static/img/shield-logo.svg`,
  with an empty alternative text because the adjacent summary conveys its meaning. Legacy Font Awesome
  dashboard classes were removed. Caret rotation selectors target the dashboard
  caret class so expanded-state and reduced-motion behavior are preserved.
- Template regression tests cover native icon names, filled-star state and
  decorative accessibility attributes; dashboard HOOT selectors use native markup.
