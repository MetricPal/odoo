# Technical-only Omni-Channel administration

The user's approved 2026-10-08 direction supersedes the earlier standalone UI.
Implemented as version 20.0.1.8.0.

## Interface

Settings → Technical → Omni-Channel precedes Email. Both are children of
base.menu_custom; the mail module sets Email to sequence 3. Omni-Channel uses sequence 2,
after the earlier-created Activities section under Odoo’s sequence/id ordering.
The resulting order is Discuss → Activities → Omni-Channel → Email.
The existing phone_validation dependency remains available for native phone tools.
Technical navigation requires developer mode and system-administrator access.

Only four destinations remain:

- Channels: standard list/form; Connections and Messages buttons; sender and
  inbound endpoint configuration in tabs.
- Messages: existing operational message/approval records.
- Policies: existing receiving and retention authorization.
- Blocklist: existing identity blocks and explicit confirmation.

Channel Operations retains receiving-policy access and expandable links to
delivery logs, intake logs, purpose audit history and recipient authorization.
Purpose membership remains accessible through the channel's relational field.
No standalone launcher, Overview, welcome screen, six-step wizard, Inbox menu,
Monitoring menu or redundant configuration tree remains. The module is no longer
marked as an application. Removed XML IDs and the setup transient are cleaned up
by Odoo's normal module upgrade process.

Existing scoped inbox actions remain available for consuming business modules;
this change does not implement new business-app integrations.

## Runtime and security

No provider runtime was replaced. Single-sender uniqueness and health-gated
activation, immutable endpoint ownership, multiple receiving endpoints,
blocklist-before-processing, company/purpose record rules, message approvals and
audit history remain enforced. Catalog-wide mocked tests exercise the standard
configuration path; working adapters are still required for actual providers.

New channel shortcuts validate system-administrator access and channel scope,
then open existing actions with filtered domains and creation defaults.
Configuration menus explicitly replace their group membership on upgrade:
Odoo's menuitem groups attribute adds groups and would otherwise retain previous
Omni Administrator access. Runtime roles remain usable by business integrations.

## Verification

Targeted administration/UI upgrade testing initially caught legacy menu groups.
The correction uses explicit group_ids replacement. Portal tests correctly
expect Odoo to deny access to the menu model entirely.

- Full upgrade regression: **139 tests passed, zero failures/errors**, including
  browser, transaction, sender health, ownership, blocklist and Telegram tests.
- Clean installation: **4 administration tests passed, zero failures/errors**.
- Ruff passes for the administration model and tests; diff whitespace check passes.
- Tests verify all four menu entries are system-admin-only, no launcher or setup
  model remains, connection defaults stay scoped, and the generic catalog works
  through the same configuration methods using mocked provider checks.

Test environment: disposable PostgreSQL on /tmp:55432, database omni_spec_test
for upgrade, omni_technical_clean for fresh installation. No business database
or real external account was upgraded, activated, connected or messaged.

Full regression command:

    PYTHONPATH=/tmp/omni-spec-deps .venv/bin/python odoo-bin \
      -d omni_spec_test --db_host=/tmp --db_port=55432 --db_user=moshkou \
      --addons-path=addons -u omni_channel,omni_telegram --test-enable \
      --test-tags=/omni_channel,/omni_telegram,-omni_capacity \
      --stop-after-init --http-port=8079 --max-cron-threads=0 \
      --data-dir=/tmp/omni-spec-data --logfile=/tmp/omni-technical-verified.log

Fresh install uses -d omni_technical_clean -i omni_channel,omni_telegram,
--test-tags=/omni_channel:TestOmniAdministration, --no-http,
--data-dir=/tmp/omni-technical-clean-data and
--logfile=/tmp/omni-technical-clean.log. The capacity benchmark is outside this
navigation change.

## Form clarity update — 20.0.1.9.0

Labels now occupy their own full-width line above inputs; forms use two columns
on desktop and one on mobile. Retention settings describe the actual stored
content next to each field. Blocklist drafts select a connection to fill scope
automatically, with server-side mismatch validation. Provider details and audit
history are secondary, and existing blocks remain compatible.

Technical Messages now uses a separate read-only monitor with status filters,
rather than the business composition view. Business actions still use the
original approval flow. Channel configuration warns when no adapter is installed:
the catalog alone does not connect WhatsApp, LinkedIn or other providers.

141 full regression tests passed, followed by 7 final administration and
desktop/mobile UI tests. Evidence: /tmp/omni-clarity-full.log and
/tmp/omni-clarity-final.log. Screenshots reviewed. No live database upgrade.
