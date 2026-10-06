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
