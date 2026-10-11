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
- Odoo Calendar extends `res.users.unlink()` in `addons/calendar/models/res_users.py`
  and removes related `calendar.user` membership records before deleting the
  user. `calendar.user` delete access is limited by record rules to own
  memberships or owned calendars (`addons/calendar/security/ir.access.csv`).
  Therefore a user who can delete another `res.users` record may still fail on
  Calendar cleanup unless that cleanup uses elevated access.

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
- Odoo 20 defines the shared authentication shell in `web.login_layout`, the
  password login form in `web.login`, the OAuth provider block in
  `web.login_oauth`, and the reset-password form in
  `auth_signup.reset_password`. The `auth_oauth` module injects enabled
  providers into `web.login_oauth`; it does not own the form order. Because
  Website globally replaces `web.login_layout`, `auth_magic_link` routes auth
  pages through its standalone copy, so branding applies the logo/footer
  changes to that active standalone layout. Branding moves the single
  `web.login_oauth` call before both the user-switch component and login form,
  with the divider inside `web.login_oauth` after provider buttons. Page titles
  are owned by page bodies, not the shared layout: login/user-switch renders the
  single `Turn complexity into clarity` title, while reset-password removes
  OAuth entirely and renders its single reset heading plus explanatory subtitle
  before the form.
- Authentication pages verified in the local Odoo 20 source are `/web/login`
  (`web.login`), `/web/signup` (`auth_signup.signup`), `/web/reset_password`
  (`auth_signup.reset_password`), `/web/login_successful`
  (`web.login_successful`), and `/web/login/totp`
  (`auth_totp.auth_totp_form`). Magic-link routes under `/auth/magic-login`
  consume tokens and redirect/authenticate; they are not standalone pages.
- The standalone authentication layout is the shared place for global auth
  chrome. Branding replaces Odoo's database-manager/powered-by footer there with
  the company name, fixed product-year text `© 2026 .`, and the Website
  application's standard `/privacy` link. The footer is part of a full-height
  flex layout and uses `mt-auto` so it stays at the bottom of the auth viewport
  when content is short, while remaining in normal document flow on shorter
  screens.

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

## Approval mechanisms

- This Odoo 20 Community source tree does not include a standalone `approvals`
  addon. Approval behavior is implemented inside individual applications as
  model-specific state machines, groups, buttons, activities, and chatter.
- Odoo 20 models inherit the standard ORM audit fields `create_date` and
  `write_date`; approval center approver lines can expose these readonly fields
  in XML list/report views without adding custom columns to
  `approval.center.approver`.
- Approval Center's `action_approval_center_requests` and
  `action_approval_center_submitted_requests` both use the same
  `approval.center.request` kanban/list/form views. A list-view change for
  Approval Requests also affects the To Review list; do not duplicate the list
  view only to add submitted-only columns.
- Odoo 20 list views support `optional="hide"` for hidden-by-default columns.
  Use it for audit fields such as `create_date` and `write_date` when users may
  need the columns without making them part of the default scanning surface.
- Kanban templates must preload every field used through `record.<field>` or a
  `<field/>` node inside the card. For request audit dates, declare `state`,
  `create_date`, and `write_date` at kanban root level before using conditional
  card blocks.
- Keep labels and values intentionally separate in kanban cards. If the design
  asks for only the timestamp, render only `<field name="create_date"/>` or
  `<field name="write_date"/>`; avoid hard-coded "Created On" / "Updated On"
  text in the card body.
- Purchase approval is implemented on `purchase.order`. Company settings
  `po_double_validation` and `po_double_validation_amount` control whether
  orders above the threshold move from RFQ/RFQ Sent to `to approve` instead of
  `purchase`. `button_approve()` writes state `purchase` and `date_approve`;
  `_approval_allowed()` permits one-step approval, below-threshold orders, or a
  user in `purchase.group_purchase_manager`.
- Expenses approval is implemented on `hr.expense`. Draft expenses are submitted
  with `action_submit()`, become `submitted` unless auto-validated, and
  `action_approve()` checks permissions/duplicates before `_do_approve()` writes
  `approval_state = approved`, approver, and approval date. Review activities use
  `hr_expense.mail_act_expense_approval`; access is driven by Expense groups
  such as Team Approver, All Approver, and Administrator.
- Time Off approval is implemented on `hr.leave` and `hr.leave.allocation`.
  Validation policy comes from work-entry type fields such as
  `leave_validation_type` and `allocation_validation_type`. Supported patterns
  include no validation, manager approval, HR approval, and two-step approval.
  Pending states include `confirm` and `validate1`; final approved state is
  `validate`. Approval activities use Time Off activity types for first and
  second approval.
- Maintenance requests contain an `approved` state, but it is a lightweight
  request state rather than a general approval framework.
- Odoo Studio approval rules exist in official Odoo 20 documentation as a
  configurable button-level approval mechanism, but Studio is not present in
  this Community source tree. The Odoo Approvals application is documented as a
  separate Odoo app/product feature, not as a Community addon available in this
  repository.
- For module identity research, use proper Odoo-style names, descriptions, and
  icons. The Odoo Approvals app icon reference provided for comparison is
  `https://download.odoocdn.com/icons/approvals/static/description/icon.svg`;
  treat it as a visual reference unless an implementation explicitly downloads
  or vendors an approved asset.
- For this project, a reusable AI-native Approval Center should not assume a
  built-in Community approval engine. It should define its own approval object
  and policy layer, then execute approved work through Odoo app-specific actions
  such as `button_approve()` or `action_approve()` where appropriate. The
  Approval Center must not bypass those actions with direct state writes unless
  the target module has no action API and the implementation records why.
- Every approval execution path must evaluate project approval policy before the
  Odoo action runs and must create an audit trail after execution, including
  actor, policy, target record, action called, result, timestamp, and failure
  reason when execution is blocked or fails.
- Odoo's user-facing Approvals product is category/request first: users create
  approval requests from approval categories/types, while each category defines
  which request fields are hidden, optional, or required, who the approvers are,
  whether approvers act in sequence, and how many approvals are required. The
  requester should not have to know a target model or method name.
- Odoo 20 Studio approval rules confirm the same separation for action-backed
  approvals: an approval rule is attached to a button/action, approvers can be
  specific users or a group, activities are created for approvers, and approvals
  are tracked in chatter and approval entries. Source:
  <https://www.odoo.com/documentation/20.0/applications/studio/approval_rules.html>.
- Odoo's Approvals feature page describes the same product shape for request
  categories: configure what information is required or optional for each
  approval type. Source: <https://www.odoo.com/app/approvals-features>.
- The project `approval_center` addon therefore exposes Approval Types,
  Approval Requests, Approver(s), and Approval Audit. `approval.center.policy`
  remains the internal model name for compatibility with the first foundation
  pass, but its user-facing description and menus are Approval Type. Approval
  Types are managed from Configuration and define icon, description, request
  field rules (`required`, `optional`, `none`), default approvers, optional
  employee manager approval, approver sequence, and `approval_minimum`
  defaulting to 1. Requests expose only fields whose type rule is `required` or
  `optional`; rules set to `none` stay hidden. Configured approvers are copied
  when a request opens from an Approval Type dashboard card, when the category
  changes, and again before submit if the request still has no approvers.
  Requests count approvals against the type minimum. Target model/action fields
  are kept as hidden technical execution plumbing for integrations, not as
  requester-facing fields. Approver lines enforce uniqueness per approval type
  and per approval request. Approval Type approver configuration is
  administrator-controlled; request owners may manage approver lines on their
  own request records, and approvers may update their own approver line status.
  On submit, requests schedule review activities with a visible summary and
  explicitly notify active approver partners through Odoo's `message_notify()`
  path; delivery as inbox or email follows each user's Odoo notification
  preference and the configured outgoing mail server.
  Inactive Approval Types follow Odoo archive behavior and remain recoverable
  from Configuration by using the Archived search filter.
- The default Approval Types seeded by the module are Business Trip, Borrow
  Items, General Approval, Contract Approval, Payment Application, Car Rental
  Application, Job Referral Award, and Procurement.
- Odoo 20 `ir.actions.report` records use `report_name`, `binding_model_id`,
  `binding_type`, and optional `print_report_name`; this source tree's report
  records do not use `report_file`, and Odoo 20 rejects that field during XML
  loading.

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

## Omni-Channel planning verification — 2026-10-05

Source inspected at `dbce1c66c4d1f9779f55d82657e8214d2c09654b`.

- Verified `ir.access` in `odoo/addons/base/models/ir_access.py`: grouped grants
  and group-less restrictions; operation/domain fields and company_ids domain
  context. Omni must not introduce legacy ir.model.access CSV assumptions.
- Verified `check_access` / `has_access` in `odoo/orm/models.py` and partial
  `UniqueIndex` support in `odoo/orm/table_objects.py`. Selected sender needs a
  partial unique index plus transactional activation protection.
- Verified `_trigger` and `_commit_progress` in
  `odoo/addons/base/models/ir_cron.py`. The latter commits; external dispatch
  therefore needs explicit worker transaction boundaries and uncertainty handling.
- Inspected HTTP verification in `addons/payment_stripe/controllers/main.py`;
  use original request bytes and protocol-specific verification, not copied
  payload logging. Inspected bus notification guidance in
  `addons/bus/models/bus.py`: prefer authorized listener surfaces.
- Inspected existing Approval Center execution, audit and access files. Omni
  needs immutable command/policy snapshots, exact target/action restrictions,
  company/purpose isolation, one-shot enqueue and persistent worker failure
  evidence. Existing generic action dispatch is not evidence those guarantees
  already exist. Changes should be scoped to Omni-linked approvals and tested
  against existing Approval Center behavior.
- `addons/social_media/__manifest__.py` is company social configuration, not a
  verified Community social publishing engine. Core must not assume Enterprise
  Social Marketing models exist.
- Official Odoo 20 ORM/index pages were available; the actions page could not
  be retrieved twice. Cron behavior was verified from this checkout, not older
  documentation. Provider and reliability sources, limitations and release gates
  are recorded in the [Omni research dossier](../exec-plans/active/odoo_omnichannel_design_v2/13-research-and-provider-readiness.md).

This is source/planning evidence only. No Omni code, module installation,
production database changes or live provider tests were performed in this pass.

## Omni-Channel foundation implementation — 2026-10-06

- `addons/omni_channel` installs and upgrades on the isolated
  `omni_build_20261006` database. No existing ERP database was upgraded.
- Required stored related company/purpose fields on sender/endpoint models
  need `precompute=True` (and no inherited default on related company) to satisfy
  INSERT-time NOT NULL constraints in this source revision.
- Verified partial `models.UniqueIndex` enforcement with independent PostgreSQL
  transactions: a competing selected-sender update waits, then fails uniquely.
- Odoo 20 relation-domain traversal on approval lines needs an explicit
  `request_id = False` branch to preserve policy approver visibility. The new
  Omni restrictions cover linked requests while ordinary Approval Center
  submit/approve/execute remains tested.
- Native Many2one `widget="radio"` renders the runtime-sender choice. Headless
  Chrome verifies the channel kanban, form action and dialog. Action dictionaries
  require an explicit name for a meaningful dialog title.
- Full verification and outstanding transport/inbox work are tracked in the
  [implementation report](../exec-plans/active/odoo_omnichannel_design_v2/15-implementation-status.md).

## Omni-Channel inbox — 2026-10-06

Base revision: `3fb2ca8b01c1`. Verified the current Odoo 20 checkout before implementing the inbox.

- HTTP is a package here, not the older `odoo/http.py` layout. Verified route `max_content_length` handling in `odoo/http/dispatcher.py`, and `odoo/http/retrying.py` committing the transaction before returning a successful response. The endpoint uses `auth='public'`, protocol verification instead of CSRF, no saved session, and a server-bound endpoint; public users have no inbox ORM grants.
- Verified `ir.access` operation selection in `odoo/addons/base/models/ir_access.py`: Read/Update is `ru`, not `rw`. Module-upgrade validation caught and corrected this during development. Company/team restrictions remain group-less CRUD domains with grouped grants.
- Verified ORM environments/transactions in `odoo/orm/environments.py`, independent cursors and savepoints in `odoo/sql_db.py`, and native uniqueness objects in `odoo/orm/table_objects.py`. The event's account relation is required and precomputed so deduplication is enforced at INSERT, not only after a deferred compute.
- PostgreSQL REPEATABLE READ behavior is tested with separate sessions: company row-version guard, concurrent unique-key insert and stale worker after a committed block. HTTP database retries are safe because intake has no external effects. Outbound transport still runs outside retryable transactions.
- Inspected `addons/bus/models/bus.py` and its secure listener guidance. This increment sends no bus payloads and has manual refresh; no channel name or record ID is treated as permission to subscribe.
- Native list/form/search views load during actual upgrade. HttpCase browser tests verify escaping, assignment and unavailable-reply explanation; no custom JavaScript transport/UI state machine was introduced.
- Attempted official 20.0 and master HTTP documentation URLs on 2026-10-06; both fetches timed out. Older search results were not used as Odoo 20 authority. The local checkout and executed integration tests are the evidence for these API decisions.

See `docs/exec-plans/active/odoo_omnichannel_design_v2/17-inbox-implementation-status.md` for exact test scope and known live-release limitations.

## Telegram adapter and health preflight — 2026-10-06

Base revision: `68c72f776884`. The addon uses the existing Odoo 20 model/view/access mechanisms rather than older Odoo API assumptions.

- Rechecked `odoo/http/retrying.py`: HTTP transaction serialization retries may rerun read-only provider preflight; commit occurs before the response. No send is added to a model button or webhook transaction.
- Rechecked `omni_channel` company/channel locking and the 120-second committed claim lease. Health now snapshots configuration before bounded read-only I/O, then locks and rechecks version/configuration/generation before persisting health/selection. A test changes account configuration during preflight and proves selection is refused.
- Installed the optional addon and upgraded inherited views on the isolated database. View selectors use stable field names rather than translated `string` attributes. Chrome exercised the native confirmation without approving it; screenshot inspection corrected a narrow paragraph layout.
- Full combined verification: 96 tests, zero failures/errors. See [Telegram report](../exec-plans/active/odoo_omnichannel_design_v2/18-telegram-sandbox-implementation-status.md).

## Uncached operator reply submission — 2026-10-06

Live sandbox preparation exposed an access error when an ordinary operator submitted a Telegram reply with an empty ORM cache. `omni.inbound.endpoint._allowed()` read `policy.state` through that operator, while `omni.inbound.policy` is intentionally administrator-only. Earlier fixtures warmed the policy field through a privileged environment, hiding the missing access path.

Verified current ORM field fetching/access behavior in `odoo/orm/fields.py` and `odoo/orm/models.py`, and the existing policy grant in `addons/omni_channel/security/ir.access.csv`. The private helper now reads only `policy.sudo().state` after validating endpoint ownership/binding and active channel/account/endpoint flags. Public action scope checks and policy model permissions remain unchanged. No operator access to policy records, retention settings or hash secrets was added.

The added `TestTelegramSandbox.test_operator_can_submit_with_uncached_private_policy` reproduced the failure before the fix, then passed with explicit negative policy-read assertions. `test_uncached_paused_policy_still_blocks_operator_submission` verifies revocation still blocks submission. Full isolated regression: 98 tests passed with zero failures/errors in `omni_regression_20261006`, log `/tmp/omni-policy-regression-after.log`. The connected sandbox was not used for regression fixtures. Core version 20.0.1.3.1 was then upgraded on the local connected sandbox.

Also verified `res.users._set_password` hashes explicitly assigned values in this checkout: passing False is not the same as omitting the field. The first approved setup attempt rolled back on that type error. The dedicated sandbox requester is created without setting a password, and SQL verifies its password column is NULL; no credential, invitation or email is generated.


## Restore neutralization hooks (2026-10-06)

Verified `odoo/modules/neutralize.py`: installed modules contribute `data/neutralize.sql` automatically; these files must not be added as ordinary manifest data. `odoo/modules/db.py:restore` runs neutralization before registry startup only when `neutralize_database=True` (default False). Base disables cron jobs, but custom Omni intake/dispatch controls require module hooks. Implement module-owned SQL to disable dispatch/endpoints, pause processing policies and revoke Telegram sandbox authorization while preserving command/approval/attempt history. Test the actual hook loader, repeated execution, blocked intake and zero outgoing sends on a disposable database. Raw PostgreSQL restores do not invoke these hooks; keep workers/ingress/network isolated until explicit neutralization and reconciliation.

Verification: targeted neutralization test passed, followed by **20 Telegram tests with zero failures/errors**, on disposable `omni_regression_20261006` using mocked transport. Command: `PYTHONPATH=/tmp/omni-test-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server -c odoo.conf -d omni_regression_20261006 --data-dir=/tmp/omni-regression-data -u omni_telegram --test-enable --test-tags=/omni_telegram --stop-after-init --http-port=8079 --max-cron-threads=0 --logfile=/tmp/omni-neutralize-suite.log`. Ruff and whitespace checks passed. Existing README-as-RST module-description warnings remain nonfatal. This verifies native hook discovery and SQL behavior, not an end-to-end backup/restore timing rehearsal. Live sandbox configuration was not neutralized.

## Telegram operations and release checks (2026-10-06)

The operations collector runs only in a trusted superuser Odoo shell; there is no public RPC/controller or scheduled execution. Verified current ORM state fields in `models/dispatch.py`, `models/inbox.py` and `models/foundation.py`. It returns counts, never bodies, recipients or credentials, and does not call providers. Actual ORM regression verifies non-superuser denial and a timed-out send raising an unknown-outcome critical indicator.

Odoo 20 `odoo/addons/base/models/ir_module.py:_get_desc` reads `static/description/index.html` before falling back to reStructuredText rendering. Telegram's Markdown fallback produced misleading rendering diagnostics; an explicit HTML module description avoids them and accurately states sandbox-only capabilities. `HttpCase.browser_size` is read by Chrome initialization; a 390×844 test verifies named/focusable authorization and dialog controls, visible approval explanation and dialog viewport fit. This is targeted mobile/focus coverage, not a full assistive-technology accessibility audit.
## Backend-derived channel URL — 2026-10-07

Verified `odoo/orm/models.py:get_base_url()` in checkout based on
`b49e1e4c97e2`: reads backend `web.base.url` through restricted configuration
access. The private endpoint helper uses this API, never the request Host header.
`channels.` prefixes the configured hostname, retaining existing subdomains and
not guessing registrable domains. An existing `channels.` prefix is not repeated.
Public URLs use HTTPS; localhost/IP/local-only or malformed backends yield False.

The superseded draft res.config.settings fields, view and menu were removed.
The server is already determined by deployment; deriving an address performs no
network requests, config writes, webhook registration or intake activation.

Mail source inspection verified `ir.mail_server` transport fields: SMTP username
identifies the sending account, not an operations-alert recipient. The main
`odoo20` database was inspected read-only and was not modified.

Verification: upgrade from the draft settings on disposable
`omni_settings_20261007` passed all three `omni_deployment` tests, zero
failures/errors. Tests cover domain derivation, local/invalid URL rejection,
backend changes reflected immediately in endpoint URLs, unchanged endpoint state,
and removal of manual settings fields/menu. Log: `/tmp/omni-deployment-derived.log`.

```sh
PYTHONPATH=/tmp/omni-settings-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_settings_20261007 --data-dir=/tmp/omni-settings-fresh-data \
  -u omni_channel --test-enable --test-tags=omni_deployment --stop-after-init \
  --http-port=8083 --max-cron-threads=0 --logfile=/tmp/omni-deployment-derived.log
```

Ruff on `addons/omni_channel` and `git diff --check` also passed.

Shared-provider verification: all four `omni_deployment` tests passed after adding
an endpoint URL check for every catalog provider (12 types). No provider transport
was enabled. Log: `/tmp/omni-shared-domain.log`.


## Operations alerts through native mail — 2026-10-07

Verified `addons/mail/models/mail_mail.py:create`: persists outgoing queue rows;
it does not send mail. Native mail server selection/FROM handling remains in
Odoo. `mail.mail.state` exposes outgoing/sent/exception/cancel status; keeping
`auto_delete=False` retains delivery evidence. Author is the approving internal
administrator; no SMTP credentials or guessed recipients enter the policy.

Verified `res.users` current group APIs and the core company/purpose scope rules.
Activation requires both system Settings and Omni configuration authority.
Private cron collection rechecks the author and recipients, freezes addresses,
uses a channel row lock, and writes the queue entry and counter snapshot in the
same transaction. `ir.cron._commit_progress` commits per channel only when called
in a real cron-progress context; tests do not silently commit their transactions.
Native `neutralize_database` loads the updated SQL hook. The test must flush ORM
state before invoking raw SQL; otherwise a later flush can overwrite its effects.

Eight targeted `omni_operations` tests passed, including actual Chrome confirmation
without confirming activation, restored-database disablement, permission denial,
content-free emails, scope isolation, revocation, deduplication and recovery.
Log: `/tmp/omni-operations-targeted-2.log`. No real email or provider request was sent.

Combined channel/Telegram regression passed **113 tests, zero failures/errors**,
with `-u omni_channel,omni_telegram --test-tags=/omni_channel,/omni_telegram,-omni_capacity`
on the same isolated database; log `/tmp/omni-operations-regression.log`.
Final authorization audit records bind the approving actor, recipient user IDs,
and a SHA256 of addresses/scope/interval. The eight targeted tests were rerun
for that final audit change; log `/tmp/omni-operations-final.log`.
Ruff and whitespace checks passed. No live policies, scheduler, SMTP credentials,
main database or provider registrations were changed.

## Native operations SMTP pipeline — 2026-10-07

Source verified at `5a4c70b59d41`: `mail.mail.send(auto_commit=False)` groups queued
mail through `_split_by_mail_configuration`, connects with `ir.mail_server`, and
records native sent/exception state. Native test mode normally short-circuits
transport via `_disable_send`; the new fixture temporarily enables it only with
an exact `(127.0.0.1, ephemeral-port)` SMTP connection guard and rejects SSL or
any other destination. The in-memory SMTP sink never forwards mail. Authentication
and TLS are deliberately absent in this loopback fixture.

Two new tests exercise actual SMTP sockets through unmodified native queue/server
selection and message generation: accepted alert plus recovery; and a deliberate
451 DATA rejection with retained failure state and no duplicate on collection.
Assertions inspect the captured MIME subject/body/recipient, native `sent` and
`exception` states, and the channel's related delivery status. No mail server is
pinned on the mail record. Fixture mail-server changes and queue rows roll back;
`auto_commit` is not enabled.

All **10 `omni_operations` tests passed, zero failures/errors** on disposable
`omni_settings_20261007`; log `/tmp/omni-alert-smtp.log`. Expected rejection logs
are asserted failure-path evidence, not suite failures. Command:

```sh
PYTHONPATH=/tmp/omni-settings-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_settings_20261007 --data-dir=/tmp/omni-settings-fresh-data \
  -u omni_channel --test-enable --test-tags=omni_operations --stop-after-init \
  --http-port=8083 --max-cron-threads=0 --logfile=/tmp/omni-alert-smtp.log
```

This verifies SMTP acceptance and explicit rejection on loopback. It does not
verify real mailbox delivery, TLS/authentication, spam handling, or operator
acknowledgement. No external email, production configuration or live policy was
changed. Ruff and whitespace checks passed. This increment changes tests/docs
only; runtime behavior and module version are unchanged.

## Native uninstall and database-scoped readiness — 2026-10-07

Verified current `ir.module.module.button_immediate_uninstall`, `button_uninstall`
and `module_uninstall`, plus `odoo/modules/loading.py` hook/uninstall order.
Immediate uninstall commits and rebuilds the registry; it must be rehearsed on a
separate disposable database, not inside an ordinary TransactionCase. Core removal
deletes owned tables and columns; ORM record restrictions are not retention guards.

Actual native lifecycle evidence on synthetic copies:
- `omni_uninstall_20261007`: Telegram removal retained unknown command 48, account
  56, synthetic audit event, and unrelated approval 33. Core removal deleted Omni
  command/audit tables; generic approval 33 remained and draft 34 could be created.
  Logs: `/tmp/omni-uninstall-telegram.log`, `/tmp/omni-uninstall-core.log`,
  `/tmp/omni-uninstall-final.log`.
- `omni_adapter_uninstall_20261007`: before fix, adapter_ready remained True after
  native Telegram removal in the same process. After fix, native install/uninstall
  gave True/False, while the global Python factory remained loaded. Log:
  `/tmp/omni-adapter-lifecycle-fixed.log`.
- Same process with both the installed regression DB and the uninstalled lifecycle
  DB: catalog readiness and `installed_adapters(env)` correctly differed. Log:
  `/tmp/omni-adapter-two-databases.log`.

The trusted registry now records owning addons; readiness filters by installed or
upgrading module state in the current database. It never unregisters a factory
needed by another database. Existing transport lookup remains process-local and
existing credential/authorization guards remain mandatory. Readiness is neither
provider health nor permission to send.

Two `omni_lifecycle` tests passed (state transitions, missing addon, persistent
loaded factory). Full isolated channel/Telegram regression passed **117 tests,
zero failures/errors**, with the command below. SMTP integration is loopback-only;
no external mail/provider request, production configuration or live data changed.

```sh
PYTHONPATH=/tmp/omni-settings-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_settings_20261007 --data-dir=/tmp/omni-settings-fresh-data \
  -u omni_channel,omni_telegram --test-enable \
  --test-tags=/omni_channel,/omni_telegram,-omni_capacity --stop-after-init \
  --http-port=8083 --max-cron-threads=0 --logfile=/tmp/omni-lifecycle-regression.log
```

Ruff on both addons and `git diff --check` passed. Core version 20.0.1.4.1 and
Telegram 20.0.1.0.1. Actual active-webhook retirement and retention approval for
live core decommissioning remain operational gates, not claimed by this rehearsal.

## Operations alert transaction isolation — 2026-10-07

Source baseline `71656b18ea67`. Verified `omni.channel._lock()` and
`_collect_operations_alert()`: the row lock serializes collection, and native
mail creation, audit insertion and snapshot update share the caller's transaction.
Added independent physical PostgreSQL cursor tests, with real commits and no
mocked locks or simulated serialization exceptions.

- Concurrent collectors: `pg_blocking_pids` proves the second backend waits on
  the first collector. On the first commit, the stale transaction receives a real
  PostgreSQL serialization failure. A fresh-transaction rerun sees the persisted
  snapshot; exactly one mail row and alert audit event remain.
- Failure after mail insertion: forced flush then exception rolls back the mail,
  audit and snapshot; a clean retry queues exactly one alert.
- Failure after snapshot flush: all related writes are already issued to SQL,
  but rollback still removes mail/audit/snapshot together; retry queues once.

The module-loading test harness holds `Registry._lock`, so the competing worker's
isolated environment is created before thread handoff, and cursor rollback/cleanup
runs on the parent test thread. Collection itself and SQL lock contention run on
the worker thread. Early fixture runs blocked on registry setup/cleanup; those
were harness failures, not claimed concurrency evidence. The final tests observe
actual PostgreSQL blocking and pass without modifying runtime behavior.

Authorization is deliberately bypassed only for these uniquely named committed
fixtures; the ordinary alert suite separately covers real roles and revocation.
External sending raises immediately if attempted. Committed mail/message/audit/
channel/purpose fixture records are cleaned afterward using their specific IDs.
Use disposable databases only. A transaction retry is demonstrated explicitly;
this does not assert that every scheduler failure is retried immediately or that
SMTP delivery is exactly once.

Three focused transaction tests passed, followed by all **13 combined alert
checks**, zero failures/errors, on `omni_settings_20261007`. Logs:
`/tmp/omni-alert-transactions-focused.log` and `/tmp/omni-alert-reliability.log`.

```sh
PYTHONPATH=/tmp/omni-settings-deps /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_settings_20261007 --data-dir=/tmp/omni-settings-fresh-data \
  -u omni_channel --test-enable --test-tags=omni_operations,omni_operations_transactions \
  --stop-after-init --http-port=8083 --max-cron-threads=0 \
  --logfile=/tmp/omni-alert-reliability.log
```

Ruff and whitespace checks passed. Only tests/documentation changed; no module
version bump, main database update, live alert activation or external email.

## Channel operator assignments (2026-10-07)

Navigation/correction follow-up: verified `RedirectWarning` in
`odoo/exceptions.py`, `RedirectWarningDialog` in the native web error handlers,
and `FormErrorDialog`/`FormController` redirect handling. Native warnings accept
an action dictionary; use a form action with exact `res_id` and `target='new'`
to open correction settings in a dialog without custom error HTML or JavaScript.
The action still uses normal record access. Group menu entries using native
`ir.ui.menu.parent_id`; retain leaf actions and restrictions.

Navigation follow-up verification: all 16 focused operations tests passed,
including the browser flow selecting an invalid operator, reading the specific
instruction, opening the exact team in a dialog and discarding the unsaved
channel draft. The preceding 126-test regression run passed the other 125 tests;
its one failure was the new browser cleanup assertion, corrected to use Odoo's
native saved-form indicator before the passing targeted rerun. No production
code changed after that full run. Ruff and whitespace checks passed. Logs:
`/tmp/omni-navigation-regression.log`, `/tmp/omni-navigation-final-tests.log`.

Local `odoo20` upgraded to 20.0.1.5.1 after a private native database/filestore
backup at `/tmp/omni-deployment-20261007/odoo20-before-navigation.zip`.
Ten business/access/mail table fingerprints and seven Omni configuration
fingerprints matched the pre-upgrade baseline. Installed menu/version verified.
The native SIGHUP reload stalled under the VS Code debugger. With no active
database transactions, the identified stalled app process was stopped and Odoo
was recovered outside the debugger with the same `--config=odoo.conf` settings.
`/web/health` returned HTTP 200. The former debug session ended; local service
output is private at `/tmp/omni-deployment-20261007/local-odoo-recovery.log`.

Verified local Odoo 20 `odoo/orm/models.py`: `_check_field_access` enforces
field `groups` on writes; `_validate_fields` runs declared constraints for
changed fields. Use native restricted Many2one fields and constraints covering
operator, company and purpose changes. Existing Omni scope record rules and
audit insertion remain authoritative; assignments do not grant user groups.

Validation: 13 targeted operations tests and then 123 full Omni-Channel/Telegram
tests passed on the isolated restored database (capacity tests excluded), including
browser rendering, restricted create/write, invalid identities, company/purpose
changes, clearing, copying and another provider. Ruff and whitespace checks passed.
Logs: `/tmp/omni-operator-tests.log`, `/tmp/omni-operator-regression.log`.

```sh
OMNI_TELEGRAM_SANDBOX_NETWORK=0 PYTHONPATH=/tmp/omni-settings-deps \
  /home/moshkou/workspace/odoo/odoo-venv/bin/python odoo-bin server \
  -c odoo.conf -d omni_deployment_20261007 \
  --data-dir=/tmp/omni-deployment-20261007/rehearsal-data \
  -u omni_channel,omni_telegram --test-enable \
  --test-tags=/omni_channel,/omni_telegram,-omni_capacity \
  --stop-after-init --http-port=8083 --max-cron-threads=0 \
  --logfile=/tmp/omni-operator-regression.log
```

## 2026-10-07 — Omni default system administrator access

- Checked local Odoo 20 source at `026b3ed9bfbc91a67e80755d755ca8fc83fddb88`:
  `odoo/addons/base/models/ir_access.py` uses group permissions intersected with
  global restrictions; its evaluation context exposes `user` and selected
  `company_ids`. An extra group grant alone cannot override a global restriction.
- `res_users.py` derives `all_group_ids` from group implication. Therefore
  `base.group_system` can imply the Omni manager role for existing and new admins.
- Consulted the official 20.0 security documentation:
  https://raw.githubusercontent.com/odoo/documentation/20.0/content/developer/reference/backend/security.rst
  It still documents the older split access/rule models; actual local `ir.access`
  source is authoritative for this implementation.
- Omni scope domains and Python constraints exempt system administrators from
  purpose enrollment only. Company selection and execution governance stay in force.
- Deployment requires upgrading `omni_channel` to 20.0.1.5.2 and restarting Odoo.
- Validation: isolated PostgreSQL 16 database, fresh module installation (20
  foundation tests passed), followed by module upgrade and 85 passing tests
  across Foundation, Commands, Inbox, Dispatch, and OperationsAlerts (zero
  failures/errors). Invocation:
  `.venv/bin/python odoo-bin -d omni_admin_test --db_host=/tmp --db_port=55432 --db_user=moshkou --addons-path=addons -u omni_channel --test-enable --test-tags=/omni_channel:TestOmniFoundation,/omni_channel:TestOmniCommands,/omni_channel:TestOmniInbox,/omni_channel:TestOmniDispatch,/omni_channel:TestOperationsAlerts --stop-after-init --no-http --max-cron-threads=0 --data-dir=/tmp/omni-admin-data --logfile=/tmp/omni-admin-regression.log`.
  Browser tests and live database deployment were not performed.

## 2026-10-07 — Setup and operator entry

- Verified Odoo 20 `ir_actions.py::_can_execute_action_on_records`: a server
  action without explicit groups requires model write access. The read-only
  workspace routing action therefore explicitly allows `group_omni_user`
  and checks group membership in its model method; operators need no channel
  write permission.
- Verified `ir_ui_menu.py::_visible_menu_ids`: each child action menu is
  evaluated independently. Setup/monitoring child menus now carry administrator
  groups directly, rather than relying only on their parent folder.
- New guide uses native TransientModel, window/server actions, notebook pages,
  view modifiers, and standard context defaults. All referenced fields and
  combined views validated by upgrading core and Telegram together.
- Telegram discovery reads only a validated scoped deployment bundle through
  the adapter secret boundary; only the public bot ID returns to the form.
  Sender/endpoint defaults preserve existing provider validation and activation.
- Final test run: 65 passed, zero failures/errors, including five Chrome browser
  tests. Command:
  `PYTHONPATH=/tmp/omni-ui-deps .venv/bin/python odoo-bin -d omni_admin_test --db_host=/tmp --db_port=55432 --db_user=moshkou --addons-path=addons -u omni_channel,omni_telegram --test-enable --test-tags=/omni_channel:TestOmniSetup,/omni_channel:TestOmniInbox,/omni_channel:TestOperationsAlerts,/omni_channel:TestOmniUI,/omni_telegram:TestTelegramSandbox,/omni_telegram:TestTelegramProvider --stop-after-init --http-port=8079 --max-cron-threads=0 --data-dir=/tmp/omni-admin-data --logfile=/tmp/omni-journey-final.log`.
  Tests use synthetic provider fixtures; no live Telegram account was connected.

## 2026-10-08 — Omni-Channel specification alignment

Verified against local Odoo 20 Community commit
`026b3ed9bfbc91a67e80755d755ca8fc83fddb88` (`odoo/release.py`: 20.0).
The official [Odoo 20 documentation source](https://github.com/odoo/documentation/tree/20.0/content/developer)
was located; implementation details were checked in the actual local source.

- `odoo/addons/base/views/base_menus.xml`: Technical is `base.menu_custom` under
  Settings, gated by developer mode; the Omni section additionally requires
  `base.group_system`.
- `addons/web/static/src/views/fields/radio/radio_field.js`: native radio supports
  Many2one selection and dynamic domains. Existing sender selection is reused.
- Existing Odoo action/transient/view mechanisms support explicit view IDs,
  modal configuration actions, statusbar and native HTML details/summary.
  Fresh install, upgrades and Chrome HttpCase tests validate the merged views,
  including Telegram view inheritance.
- Runtime reuse: sender health checks/generation locking/unique index, inbound
  ownership and blocklist checks, approved processing policy and append-only audit.
- Added server-controlled endpoint verification status and a provider-neutral
  wizard. No external send is performed by health verification.
- Full regression: 145 tests, zero failures/errors, isolated `omni_spec_test`,
  `/tmp/omni-spec-final.log`. Capacity benchmark excluded. Final focused validation
  and exact commands are in the specification implementation report.

Final checks: 15 setup/UI tests pass in `/tmp/omni-spec-visual-final.log`; clean
installation with 8 setup tests passes in `/tmp/omni-spec-fresh.log`. Native
`odoo/tools/convert.py` returns one ID for `<value search=...>`; category seeding
uses nested `search`/`write` functions (as in `website_sale_stock` data) to update
the full catalog recordset. Protected original catalog XML IDs remain noupdate.

## 2026-10-08 — Email-style technical administration

User-approved simplification supersedes standalone Omni navigation (20.0.1.8.0).
Verified local source:
- addons/phone_validation/views/phone_blacklist_views.xml:
  phone_validation.phone_menu_main, parent base.menu_custom, sequence 3.
- odoo/addons/base/views/base_menus.xml: Technical belongs under Settings and
  is developer-mode gated; sequence 4 puts Omni before native Actions at 5.
- odoo/tools/convert.py: menuitem groups uses Command.link, so upgraded menus
  explicitly replace group_ids to remove legacy role grants.
- odoo/addons/base/models/ir_ui_menu.py: debug visibility and user-root APIs
  support tests for technical-only access and absence from the app launcher.

Channel shortcuts reuse existing act_window actions and normal access checks.
Standard module cleanup removes obsolete menus/actions/views and the transient
wizard, while preserving channel/account/sender/endpoint/message/audit models.
See 11_technical_administration.md for final test results.

Final technical-only validation: 139 upgrade/regression tests passed in
/tmp/omni-technical-verified.log; 4 clean-install administration tests passed in
/tmp/omni-technical-clean.log. Both runs reported zero failures/errors. No live
business database upgrade or external provider activation was performed.

## 2026-10-08 — Clear forms and message monitoring (20.0.1.9.0)

Verified native primary inherited views and explicit act_window.view bindings
against the local view engine through upgrade and Chrome tests. The technical
Messages action now selects a read-only primary form; business composition
continues using its original action. All three redesigned forms use explicit
label/field containers, avoiding group cell misalignment.

Block connection defaults and mismatched-scope rejection are exercised in ORM
tests. Full regression: 141 tests, zero failures/errors
(/tmp/omni-clarity-full.log). Final administration plus desktop/mobile geometry
and monitor-control checks: 7 tests, zero failures/errors
(/tmp/omni-clarity-final.log). Reviewed desktop screenshots for policy, blocklist
and monitoring and the 390px mobile policy screenshot. Ruff and diff whitespace
checks passed. Capacity benchmark excluded; no live database upgrade performed.

## 2026-10-08 — Effective Email menu order correction

addons/mail/views/mail_menus.xml overrides base.menu_email to sequence 3;
Discuss uses 1 and Activities uses 2. The earlier check of base alone missed
this override. ir.ui.menu orders by sequence,id. Omni uses sequence 2 after the
earlier-created Activities record. Tests assert immediate adjacency to Email
and preserve both Discuss and Activities ahead of Omni.

### Channel readiness badge (2026-10-08)

Verified the Odoo 20 native badge field in `addons/web/static/src/views/fields/badge/badge_field.js`: selection fields and conditional semantic decorations are supported. Channel readiness now appears without a label at the top right of the form sheet, with success, warning and danger colors. The empty sender selection error now names the Outbound senders tab. No activation or permission behavior changed.

### Workflows research (2026-10-09)

Verified Odoo 20 source: base_automation supports on_create, on_write,
on_time and on_webhook, trigger fields and domain filtering. Its callbacks
execute server actions under elevated access; Workflows must explicitly switch
back to its approved execution user and company. ir.actions.server.run supports
native record updates/creation, activities, followers, messages and Python.
The native webhook action uses postcommit fire-and-forget callbacks, so it
cannot supply durable step failures; tracked workflow webhooks need a separate
executor. Approval Center provides policy-defined approvers, review permissions
and request state; Workflows will reuse these requests. OWL client actions use
the action registry, ORM service and standard form dialogs.

Workflows implementation findings:
- Odoo 20 has `ir.access` with CRUD operation strings and domains; it has no
  `ir.rule` or legacy `ir.model.access` model.
- OWL 3 templates use `this` for component members and explicit parameters on
  `t-call`. Native icons use `oi` plus `data-icon`. Client action dictionaries
  returned through ORM calls must include their `views` array.
- `ir.actions.server.run` calls a sudo runner after its initial access check.
  Workflows retains the native check/dispatcher with a non-sudo execution
  environment so relational updates and created records keep their ACL checks.
- Native mail actions queue notifications with `mail_notify_force_send=False`.
  Successful workflow handoff is distinct from external email delivery.
- Activation fingerprints include executable configuration, excluding chatter
  and other changing operational metadata.

The native Create Record action only calls name_create(value). Workflows therefore
uses a small typed field-mapping form and ordinary ORM create for this step, so
required business fields (such as a purchase vendor) can actually be supplied.
Mappings accept fixed values, compatible source fields or the source record.
The target create and optional source-link write run in the same step savepoint.

Workflows verification completed on disposable databases: clean installation
passed; final regression recorded 34 tests with zero failures/errors in
`/tmp/workflows-release-check.log`. Browser checks cover both viewport sizes,
branch paths, creation mappings, preview, recovery and Approval Center return
navigation. Test providers are synthetic; this is not live delivery evidence.

Workflow app navigation: Odoo 20 `webclient/navbar/navbar.xml` renders root-menu
children as app sections. `web/search/layout` supplies the native control panel;
its `control-panel-buttons` slot places primary buttons beside the breadcrumbs.
The list controller uses a `btn btn-primary` button labelled New with hotkey `c`.
Use these mechanisms for Workflows rather than a second in-page navigation bar.

Removing the Workflows approval shortcut uses `ir.model.data._process_end` in
`odoo/addons/base/models/ir_model.py`: upgrading deletes module-owned records
whose non-noupdate XML IDs are no longer loaded. Verified removal of both the
menu and its dedicated action on the existing disposable database.


Workflow listing navigation (2026-10-10): verified native app-section rendering
in `addons/web/static/src/webclient/navbar/navbar.xml` and reused the existing
Workflows client-action registration pattern. `My workflows` is the first child
menu (sequence 5), beside the Workflows app brand, with the same administrator
restriction. It opens the moved listing and existing builder; no ownership
filter or permission change was introduced. The overview retains templates.
XML parsing, JavaScript/Python syntax, and whitespace checks passed. Browser
coverage was added for menu navigation and opening a listed workflow; execution
is pending explicit approval to create the disposable local test database after
automatic approval review rejected that database creation.

My workflows native views (2026-10-10): replaced the custom collection table
with an `ir.actions.act_window` using list, kanban, and form views. Verified
`action`/`type` row/card opening in the local list controller and kanban record,
and `records_draggable`/`groups_draggable` parsing and resequencing guards in
`addons/web/static/src/views/kanban/kanban_arch_parser.js` and
`kanban_renderer.js`. Both drag flags are false, including when users regroup
the board. The server's existing protected `state` write guard remains intact.
The new builder-opening method enforces the existing administrator and record
access checks. Extra business list fields use `optional="hide"`; technical
tokens, webhook credentials, and internal execution fields are not exposed.
The earlier client action remains as a redirect for existing bookmarks.

Validation: all module XML/Python syntax, JavaScript syntax, Odoo list/search
Relax NG schemas, and whitespace checks passed. Updated browser tests cover
view switching, non-draggable cards, optional columns, and opening the builder;
model tests cover direct status-write rejection and builder access. Runtime
tests and the running-app module upgrade have not been performed; disposable
database creation remains pending the approval requested in the previous turn.


Workflow creation page (2026-10-10): the New client action now owns the description
and document-selection panel. Overview retains templates. Verified the local
Odoo 20 ListController.createRecord override and native KanbanController on_create
route; the list extension changes only creation navigation, and kanban retains
its non-draggable flags. Start blank returns a current-target act_window with
an explicit form view and default_model_id/default_description; opening either
page does not call create. The native form supplies saving and builder access.
Updated UI coverage checks separate-page navigation and form prefilling.
XML/Python/JavaScript syntax, list/search schemas and whitespace checks passed.
Runtime tests and module upgrade remain unperformed, pending the previously
requested approval for a disposable test database.

Creation-page render fix: bundled OWL resolves bare `String(...)` in a template
expression as a context property, producing `ctx.String is not a function`.
Use `model.id.toString()` for the option selection comparison instead. Executed
the bundled compiler's expression logic locally: reproduced the original error
and verified the replacement for matching, nonmatching, and empty selections.
XML parsing and whitespace checks passed; no database changes were needed.

Workflow starter inside the form sheet (2026-10-10): New now routes directly to
the native unsaved workflow form. A registered view widget inside `<sheet>` owns
the description/document inputs and Start blank button; it is hidden for saved
records. Verified `standardWidgetProps` and `view_widgets` registration against
the local widget implementation, and the Odoo 20 many2one update shape
`{id, display_name}` against native record-update callers. The button calls
`record.update` on the form's current record rather than opening another action
or calling create/save. Native `Record.update` keeps changes local while the new
form is in edition. Only Document and Description are changed; prose is not
interpreted as executable workflow configuration.

Validation: executed the actual widget method with an in-memory record, checking
field population, preservation of existing name/trigger, saved/readonly/invalid
selection guards, and busy-state recovery after errors. XML/Python/JavaScript
syntax and whitespace checks passed. UI regression now requires the panel to be
inside the sheet and the URL/form to stay unchanged when Start blank is clicked.
Live browser verification and module upgrade remain pending.


Workflow navbar simplification (2026-10-10): removed the redundant Overview
child menu. The Workflows root keeps its existing overview action; My workflows
and Run history remain its visible sections. Module upgrade removes the obsolete
module-owned menu using the previously verified XML-ID cleanup mechanism.
Updated navigation assertions and the UI return path to use the app brand.
XML/Python syntax and whitespace checks passed; live upgrade remains pending.


Workflow overview search and layout (2026-10-10): the template gallery now uses
native WithSearch, SearchBar, and useSearchBarToggler in Layout's standard
control-panel slots (verified against the local list controller template).
Category toggles moved to search filters; Category/Application groupings partition
the template cards. A read-only `workflow.template` SQL view exposes only static
recipe metadata so native custom-filter field lookup/validation targets a real
model, not workflow definitions. It is backed by the existing recipe catalog,
with administrator read-only access and no writable template records. The UI
uses native Domain evaluation on the same metadata. The left content is a white
sheet, with separate right guidance and stacked sections on small screens.
Browser and model regression tests cover filtering, grouping, and catalog access.
Validation performed: XML/Python/JavaScript syntax, native search-view Relax NG
schema, SCSS compilation, and whitespace checks passed. Executed the actual
overview grouping getter for ungrouped, category, application, combined, and
empty-result cases, checking that cards are neither lost nor duplicated. Live
browser/model tests and the SQL-view module upgrade remain pending the previously
requested test-database approval; they are not reported as passed.

Overview filter-loading correction: Odoo 20 SearchModel only loads the search
view when `searchViewId !== undefined`. Omitting this WithSearch prop gives an
empty `<search/>`, leaving only Custom Filter visible. Explicitly passing
`searchViewId="false"` requests the model's default search view. Verified the
actual loader condition with omitted and false values, validated six category
filters and two groupings against the native schema, and strengthened the UI
regression to require every predefined menu entry. Live browser verification
has not been run for this correction.

Overview independent scrolling: Layout keeps the control panel outside its
content element. The overview now constrains that element and its grid to the
remaining height, with separate vertical overflow on the left white sheet and
right guidance section. Both are keyboard-focusable and prevent scroll chaining;
stacked narrow-screen sections retain independent scrolling. Added browser
assertions for independent scroll positions and stationary toolbar geometry.
XML/Python syntax, SCSS compilation, and whitespace checks passed; the browser
regression has not been run against a live database.


Native form styling alignment: verified `form_controller.scss`, the form
compiler, and `mail/static/src/chatter/web/form_renderer.scss` against the DOM
reference. The overview now uses `o_form_view`, `o_form_renderer`,
`o_form_sheet_bg`, and `o_form_sheet`; its guidance uses the native aside and
scroll-container structure with a sticky heading. Removed custom sheet border,
padding, and grid sizing in favor of Odoo's rules. The actual workflow form now
includes native chatter (the model already inherits mail.thread). Its starter
stays inside the sheet. Overview sections retain independent scrolling and stack
at the native XXL breakpoint. XML/Python syntax, SCSS compilation, and whitespace
checks passed; live browser verification and module upgrade remain pending.


Workflow form toolbar: registered a model-scoped form view configuration with a
custom buttonTemplate. It calls native `web.FormView.Buttons`, then renders a
native ViewButton for action_open_builder. Removed the old form header row.
Verified formView buttonTemplate forwarding, FormController's ViewButton
registration, and beforeExecuteActionButton: the standard handler saves and
validates the record before dispatching the object action. UI regression checks
button order and opening the builder with the selected document. XML/Python/JS
syntax and whitespace checks passed; live browser verification remains pending.


Overview template cards: removed the gallery heading/count and replaced custom
button cards/grid sizing with the native kanban renderer CSS structure, article
cards (`o_card_record o_kanban_record`), flex wrapping, and ghost fillers. Checked
local KanbanRenderer and CardRenderer templates and kanban styles. The overview
still owns its filtered catalog rendering; it reuses native card markup/styles.
Cards support click, Enter, and Space. Unavailable recipes and busy submissions
are guarded in fromTemplate, since aria-disabled alone does not prevent actions.
XML/Python/JavaScript syntax, SCSS compilation and whitespace checks passed;
updated UI assertions require article cards and no gallery heading. Live browser
verification remains pending.


Overview guidance relocation: removed the overview aside and expanded its native
sheet container. Moved Workflow guide and the When → If → Do explanation into
the builder immediately after Before you activate. The overview's redundant
Building blocks summary is removed; the builder retains its existing step
palette. Updated scroll and placement regression assertions. XML placement,
Python syntax, SCSS compilation, and whitespace checks passed; live browser
verification remains pending.


Overview application search panel: added native `<searchpanel>` on the template
search view and forwarded WithSearch's display configuration to Layout. The app
field is now a selection derived from distinct recipe badge values (same SQL
text values); Odoo 20 search_panel_select_range requires selection or relational
fields, not Char. Native selection-range handling supplies counters and All;
its domain combines with the top search/filter/group controls. The catalog
remains read-only, including templates for apps not yet installed. Added model
checks for categories/counters and UI coverage for selecting CRM and clearing it.
Syntax/schema/SCSS checks passed; live regression and module upgrade are pending.

Search-panel layout correction: native `.o_form_view` applies
`flex-flow: column nowrap`, which placed the full-height sidebar above the
gallery and clipped the cards. The overview content now explicitly uses
`flex-flow: row nowrap` while retaining native sheet styles. Added browser
assertions for side-by-side geometry and visible cards, rather than only DOM
presence. SCSS compilation and syntax checks passed; live verification is pending.


Overview native kanban structure correction: removed o_form_view,
o_form_renderer, o_form_sheet_bg, and o_form_sheet wrappers from this overview.
The single o_kanban_renderer is now a direct Layout content child beside the
native search panel/resizer. Article cards and ghost fillers are direct renderer
children; optional grouping labels have full width without wrapping the cards.
Removed form-layout CSS overrides and retained only scroll/flex sizing. Native
new-workflow form styling is unchanged. Structural assertions, XML/Python syntax,
SCSS compilation and whitespace checks passed; live verification remains pending.


Overview styling cleanup: removed the o_workflows CSS scope and all overview
layout overrides. Overview uses the native o_kanban_view root and Layout without
className, yielding only o_content and o_component_with_search_panel on main.
Existing builder/run-history styling is scoped exclusively to their non-overview
root; the overview no longer inherits its colors, typography, or sizing. Added
an exact main-class assertion. Native styling/structure is the documented default.
XML/Python syntax, SCSS compilation, and whitespace checks passed; live
verification is pending.


Overview Kanban/List switcher: replaced the custom catalog-rendering client page
with a native act_window on workflow.template (`kanban,list`). Native controllers
now own the renderer, pager, search state and view switcher. Added native kanban
and read-only list architectures with optional hidden detail columns; both open
templates via the same access-checked action_start method and preserve the
existing draft-creation/activation boundary. Dedicated button templates route
New to the workflow form, rather than attempting to create read-only recipes.
The old overview action remains a redirect for existing bookmarks. Removed
custom Overview/WithSearch rendering and client filtering/grouping code.
Regression coverage includes switching while CRM is selected, hidden list
columns, native action wiring, and opening a draft. XML/Python/JavaScript/schema
checks passed; browser and database tests remain pending approval.


### Native Run history views

Run history now opens an `ir.actions.act_window` on `workflow.run` with native
list, kanban and form views, a search view and an 80-row page size. Odoo owns
search/filter/grouping, switching and pagination; the previous custom 200-run
fetch and sidebar renderer are removed. Kanban drag/drop and CRUD are disabled.
Native run forms retain confirmed recovery actions and add read-checked builder
navigation. Existing client-action URLs redirect to the native window action.
Verified selectors against Odoo 20 `core/pager/pager.xml` and
`views/fields/statusbar/statusbar_field.xml`. Added browser coverage for paging,
status filtering, grouped view switching and updated recovery/navigation checks;
added model coverage for native action configuration and builder access denial.
Local syntax/schema checks are run separately from database/browser tests. A live
module upgrade and database/browser regression remain pending authorization for
the previously blocked disposable test database.


### My workflows empty status columns

The workflow state uses native Selection `group_expand=True`. Odoo 20
`odoo/orm/fields_selection.py::_default_group_expand` returns every selection
value in declaration order; this provides Draft, Active, Pause even with no
matching workflows. No custom renderer or CSS is needed; drag/drop stays off.
Regression coverage checks one draft and a completely empty domain, and the
browser navigation check asserts column order. Python syntax and diff checks
passed; database/browser execution remains pending.


### Run history empty status columns

Run kanban uses native `default_group_by="state"`; its Selection field uses
`group_expand=True` to show Running, Waiting, Failed, Done, Stopped in declaration
order, even for an empty result. Verified against Odoo 20's kanban arch parser
and Selection `_default_group_expand`. Existing drag restrictions remain.
Model regression covers a single done run and an empty domain; browser coverage
checks all five columns before and after a filter produces no matching runs.
Local Python/XML syntax and diff checks passed; database/browser tests not run.


### Builder native surrounding layout

Builder actions use Layout's `control-panel-buttons` slot, verified in Odoo 20
`search/layout.xml` and `layout.js`. The step palette uses `o_search_panel`;
the canvas uses `o_form_renderer`/`o_form_sheet_bg`, with guidance inside
`o-mail-Chatter-content d-flex flex-column flex-grow-1 bg-inherit`. Native form
and mail chatter layout rules supply the surrounding structure. The canvas and
right content have separate scroll containers. Custom canvas/node rendering
remains; the old three-column grid and palette/card shell overrides are removed.
Existing activation/preview handlers and permissions are unchanged. Updated
browser assertions target the native toolbar, left panel and right content.
Python/XML syntax, SCSS compilation, and diff checks passed. Browser tests and
live visual verification have not been run.


### Builder resize and settings refinement

Added the native `o_search_panel_resize h-100 px-2 opacity-0 opacity-100-hover`
handle and reused Odoo 20 SearchPanel `_onStartResize` for pointer bounds and
listener cleanup. Settings follows Activate/Pause and calls the same
`configureWorkflow()` handler as the previous Workflow settings button. Removed
the Before you activate section and step insertion hint; activation guards stay
unchanged. Browser regression checks cover placement and pointer resizing.
Local XML/Python/JS syntax, handler checks and diff checks passed; browser tests
remain unexecuted.


### Builder settings entry point

Removed the duplicate toolbar Settings button at the user's request. The always
present When starting-point card retains `configureWorkflow()` and opens the
workflow configuration. Updated the toolbar regression assertion and user guide.
XML/Python syntax and the starting-point handler binding were checked locally.


### Builder inline step editor and palette drag/drop

Selected steps render through native `View` and `FormController`, using the
existing `workflow.step` form. A primary inheritance of `web.FormView` adds
native Save/Discard controls above the form without a nested control panel.
Verified view `jsClass` and callback-recorder props against Odoo 20 `view.js`,
`form_view.js`, `form_controller.js`, and `action_hook.js`. Selection changes and
preview/activation first run the native form's before-leave validation/save;
failed validation retains the current editor. A confirmed deletion of the
selected step may discard its pending edits. Closing the editor restores the
guide. Active workflows use a read-only form and cannot add/remove steps.

Palette items support native browser drag events; only this builder's palette
items are accepted. Dropping on a card inserts after that step; on When inserts
at the start; blank canvas uses the current selection. Calls reuse `add_step`,
including existing sequence/branch handling and backend permission checks.
Red Remove step and per-card × controls share the existing confirmation and
unlink checks. The starting-point card is never removable.

Local isolated JS checks passed for drop targets, active-workflow guards,
invalid-edit selection guards, and confirmed deletion. Python/JS/XML syntax,
SCSS compilation, template inheritance targets and diff checks passed. Updated
browser regression exercises dragging, inline save, card removal, guide
visibility, and create-record mappings. Full database/browser tests and live
visual verification remain pending.


### Inspector starting point and removal styling

The starting-point card selects an inline `workflow.definition` form instead
of FormViewDialog. Explicit primary inherited inspector views reuse the native
workflow/step fields and set `workflow_inline_step`; the workflow variant removes
chatter and the new-workflow starter. Separate primary views avoid changing the
normal full-page forms. The inspector's scoped spacing/height rules remove
nested full-page sizing and keep one outer sidebar scrollbar. Native transparent,
borderless link-button utilities give removal controls and the top-right × red
text without a colored background. Insertion uses a numeric selected-step ID
or false, so selecting the trigger never sends its UI key to the model.
Browser regression now checks inline trigger settings, guide visibility, lack
of nested chatter, and transparent borderless removal controls. Local source,
syntax, inheritance and interaction checks are recorded separately from live
browser verification, which remains pending.


### Inspector footer buttons

Moved the native Save/Discard template after `o_form_view_container`. The inline
controller root explicitly uses Odoo flex-column utilities, and its footer uses
a horizontal, non-stretching button row. This corrects the buttons appearing as
tall columns alongside the settings fields. Added browser geometry assertions
for footer position and normal button height. Local XML/Python syntax and native
template inheritance checks passed; live browser verification remains pending.


### Inspector actions in the main control panel

Inline form actions now use Odoo's custom portal mechanism (as in native
`search/layout.xml`) to render in this builder instance's uniquely scoped
`o_control_panel_navigation`. Native form Save/Discard callbacks and ViewButton
object execution remain attached to the form controller. Remove step retains
its confirmation and red-text style. Configure action follows a vertical divider
only for editable action/foreach steps other than Create record; it uses the
native ViewButton save-before-execution path. The inspector-specific step view
removes its original header to avoid a duplicate Configure action button.
Updated browser checks cover toolbar placement and absent dividers on trigger
and wait settings. Local syntax, native inheritance and action-condition checks
passed; live browser verification remains pending.


### Palette native dragging fix

Odoo's bundled Owl `setAttribute` converts boolean true to an empty HTML
attribute. `draggable` is enumerated, so the palette must render the strings
"true" and "false", rather than booleans. Corrected the binding and added a
browser assertion for both the attribute and native `element.draggable` property
before the existing drop regression. Replaced After with a drag/click hint.
Local XML/Python checks and a regression using the checked-out Owl attribute
setter passed; live browser drag verification remains pending.


### Inspector toolbar order

Ordered inspector actions as extra actions, conditional vertical divider, Remove
step, Discard, Save. Native save/discard handlers remain unchanged. Verified
actual Odoo template inheritance and added a browser order assertion.


### Right-panel action row and selected-card highlight

Moved the form action portal into the builder's native chatter-top/topbar area.
The order is Save, Discard, Remove step (secondary), then other actions. A
horizontal rule follows the row; the previous vertical divider is removed.
Save/Discard and ViewButton execution still use the native form controller.
Removed the permanent trigger border rule: `is_selected` alone controls the
highlight and the starting point sets it only while its editor is selected.
Updated browser assertions cover placement, order, separator and single-card
selection. Local syntax, inheritance and SCSS checks passed; live browser
verification remains pending.


### Builder title and status placement

Removed the duplicated document breadcrumb/workflow heading above the canvas.
The status badge uses Layout's `control-panel-additional-actions` slot, rendered
beside the current name by native Odoo 20 Breadcrumb.Actions. Status labels remain
Draft, Active, Pause. Updated navigation assertions to use the native title and
trigger card, and added coverage for the badge and absent canvas header. Local
XML/Python syntax and diff checks passed; browser verification remains pending.


### Keep workflow breadcrumb stable during inline editing

Odoo FormController calls `env.config.setDisplayName` during loading and saving.
The embedded inspector inherited the enclosing action's setter, allowing its
loading/record title to overwrite the workflow breadcrumb (including Unnamed).
Isolated the inspector setter in its child environment. The builder now explicitly
sets its action title from `builder_data.name` on each reload, including after
saving a renamed workflow. Native FormController behavior otherwise remains.
Regression assertions cover initial title, trigger/step selection and step save.
Local syntax and isolated title-ownership checks passed; live browser execution
remains pending.


### Channels overview with communication teams

`omni_channel.action_channels` now explicitly selects native kanban/list/form
views, channel search, and an 80-record page size. The search panel uses the
existing `purpose_id` Many2one (Communication team), with counters and expanded
team choices. Existing Sales, Human Resources, Marketing and Recruitment catalog
records are reused; no team membership or channel ownership is reassigned.
Native category filters use stored channel-type categories; non-stored readiness
is displayed but is not used as a search/group field. Grouping supports team,
channel type and company. Secondary business columns are optional/hidden.
Removed the custom channel kanban shell styles and disabled card/group dragging.
Existing create/form, provider setup, access and company boundaries remain.

Verified the native search-panel approach against the workflow overview and
Odoo 20 search view schema. Database-free view-contract test, native list/search
schemas, Python/XML syntax, SCSS compilation and diff checks passed. Added a
browser regression for team filtering, view switching and native controls; that
test and a live module upgrade have not been run.


### Guided channel creation

Channels New now opens a dedicated native `omni.channel` setup form through
small list/kanban controller extensions. It has five local UI steps: details,
connections, senders, receiving, review/verify. Odoo 20 FormController owns the
record, field widgets, validation, saving, action buttons and access checks.
The setup template inherits `web.FormView`, verified with Odoo's actual template
inheritance helper. Its layout uses `o_search_panel`, native resize behavior,
`o_form_renderer`/`o_form_sheet_bg`, and a separate chatter-style guidance area.
Native action state retains the selected step across scoped connection/policy
navigation. Step changes save and stop on validation failure; no completion or
verification state is fabricated. Finish saves and opens the regular channel
form; all delivery/provider activation remains behind the existing controls.
No provider credentials, callbacks or unsupported integration flows are invented.

Added database-free layout/view tests and a browser creation regression asserting
no selected sender, dispatch or enabled endpoints. Both database-free tests,
JS/Python/XML syntax, native search/list schemas, manifest parsing, SCSS,
actual template inheritance, and isolated navigation/error/finish checks passed.
Database/browser execution and the live module upgrade have not been run.

## Telegram runtime setup (2026-10-10)

Checked local Odoo 20 `odoo/orm/fields.py`: computed inverse fields default to
non-stored and writable; runtime token inputs are consumed before ORM create/write
and recompute as false. `odoo/orm/models.py` provides record-aware `check_access`;
`odoo/addons/base/models/ir_access.py` uses `ir.access` CSV operation flags, not
older `ir.model.access` permission columns. Native Char supports `password=True`,
and `CopyClipboardChar` is registered in web's copy_clipboard field component.
`odoo/sql_db.py` exposes postrollback callbacks for cleanup of new private files.
The existing `data_dir` config option supplies credential storage location; the
active cursor supplies database scope. Module import, combined XML inheritance,
standalone credential tests and synthetic provider tests pass. Database migration,
ORM integration tests and live Telegram/browser verification remain pending.

## Multiple channels per communication team (2026-10-10)

Checked `odoo/orm/table_objects.py`: a `_scope_unique` declaration on
`omni.channel` names its PostgreSQL constraint `omni_channel_scope_unique`.
Removed only that declaration and added an idempotent pre-migration in
20.0.1.10.0. Provider identity constraints and the per-channel selected-sender
index are unchanged. Regression coverage allows same-scope active and archived
channels while still rejecting duplicate sender ownership across channels.

After explicit user approval, tested the migration twice against a PostgreSQL
temporary table (rolled back): duplicate scopes succeeded, archived rows and the
primary key were preserved. Applied the same migration to `odoo20` on 2026-10-10.
Verified after commit that `omni_channel_scope_unique` is absent, channel row
count is unchanged, and every other constraint/index on channels, accounts,
senders and inbound endpoints is unchanged. No full module upgrade was run.


### Six-step Omni-Channel setup (2026-10-10)

Verified the checked-out `addons/web/static/src/views/form/form_controller.js`
uses the ORM service, native `save()` validation and `model.load({resId})`.
The setup retains that lifecycle and calls a manager-checked server transition
before marking a forward step complete. XML inheritance is exercised against
both the core setup form and the Telegram extension using Odoo's
`apply_inheritance_specs`; no separate connection form is required by the wizard.
Draft binding preparation reuses the existing account, sender, endpoint and
policy ORM mechanisms. Enable/activate/test actions delegate to existing
permission, approval and audit actions rather than assigning final states.

### WhatsApp unchecked receipt on draft creation (2026-10-11)

Verified `addons/web/static/src/model/relational_model/record.js::_getChanges`:
new records merge initial values into save changes and omit readonly fields,
but include editable Boolean defaults even when invisible. Verified
`addons/web/models/models.py::web_save` calls `create(vals)` for a new record.
The WhatsApp receipt field's unchecked `False` is therefore normal draft input.
The WhatsApp create guard allows that neutral value and default, while rejecting
receipt confirmation, diagnostic state/fingerprint input and forged context
defaults. Regression checks use native `web_save` and roll back all records.

### WhatsApp committed diagnostic notification (2026-10-11)

Verified `odoo/modules/db.py::create/drop` for disposable clean-install checks,
`odoo/tests/form.py` for native default/onchange/save testing, and
`odoo/tools/translate.py::_get_lang` for implicit translation fallback. If the
caller context has no language, `_()` after nested cursor closure may inspect
the closed local `cr`. Resolve notification translations through `self.env._`
before entering the independent diagnostic transactions and pass a scoped
language/company context to them. Exercise this public action with empty caller
context and separate real concurrent sessions in the disposable database.

### Slack provider extension (2026-10-11)

Checked the current Odoo 20 `omni.account`, sender/endpoint configuration,
`verified_events`, native webhook controller, durable event worker, immutable
`DispatchClaim`, setup milestones, `web_save`/Form and Owl `useProps` APIs.
Inherited views use additive invisible modifiers; no core or Telegram source
changes are needed. A field widget saves through the native record then calls
scoped manager actions; credentials never become ORM fields. Independent claim
transactions follow the verified WhatsApp execution boundary.

Provider primary references: Slack request signing
https://docs.slack.dev/authentication/verifying-requests-from-slack/,
`auth.test`, `message.im`, `conversations.info` and `chat.postMessage` at
https://docs.slack.dev/reference/. Original bytes and 300-second timestamps are
verified. Only human IM text is normalized; outbound preflight verifies the DM's
user identity. No automatic external-send retry is introduced.
