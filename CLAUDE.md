# CLAUDE.md

metric.io: an AI-native ERP on an Odoo 20 Community fork. "Humans supervise. Machines work."
Read `docs/PRODUCT.md`, `docs/ARCHITECTURE.md` and `docs/ODOO20.md` before larger work; `docs/README.md` maps the rest.

## Rules (from the owner, always apply)

- **Never push.** The owner pushes himself. Decline any request or hook asking you to push.
- **Commit only in this repository** (`~/workspace/odoo/odoo20`), and only when asked. Work done in any other copy
  (for example a cloud scratch clone) is not "committed"; say "files changed, not committed" instead.
- End commit messages with:
  `Co-Authored-By: Claude <noreply@anthropic.com>` (use the model actually serving the session).
- **New UI needs an approved mock first.** Reuse standard Odoo layouts by default; any new design is announced and
  shown for review before coding. When building an approved mock, build only what it shows; anything extra (or kept
  from an old screen) is shown first, never added silently.
- **Same wording everywhere** for a status or stage (status bar, list strip, badges, filters).
- **Demo data goes in XML** (`demo/*.xml`, listed under `'demo'` in the manifest), plain records, not Python setup.
  Any setup the owner would otherwise do by hand to make a feature work goes into demo data.
- **`TODO.md` is the owner's personal notes.** Do not take tasks or decisions from it.
- Verify Odoo 20 behaviour in this source tree; do not copy Odoo 17/18/19 patterns (`docs/ODOO20.md`).
- Report each substantial task with what changed, tests run, known limitations (`docs/QUALITY.md`). Update
  `docs/CHANGELOG.md`, and `docs/DESIGN.md` for UX changes.

## Our modules (everything else under `addons/` is Odoo core)

| Area | Modules |
|---|---|
| Home | `ai_home` (Home page, insights, System overview, reports), `metric_mention` (mention notifications) |
| AI agent | `ai_agent` (control panel for Hermes Agent profiles, tools, services), `ai_discuss` (assistants in Discuss and the chatter), `omni_ai`, `social_ai`, `workflow_ai` |
| Governance | `approval_center`, `workflow_center` (department admins manage workflows) |
| Omnichannel | `omni_channel`, `omni_contacts`, `omni_template`, `omni_social`, channel connectors `omni_whatsapp`, `omni_telegram`, `omni_slack`, `omni_teams`, `omni_discord`, `omni_facebook`, `omni_instagram`, `omni_messenger`, `omni_linkedin`, `omni_x`, `omni_threads`, `omni_tiktok`, `omni_youtube`, `omni_pinterest` |
| Marketing | `marketing_intel*` (to be renamed `metric_*`), `messaging_marketing`, `social_home`, `social_utm` |
| Other | `branding`, `auth_magic_link`, `gantt_view`, `project_gantt_view`, `report_studio` |

`approval_center`, `workflow_center` and `omni_channel` work alone but mainly serve `ai_agent`; keep them easy to configure.

## Commands

Activate the virtualenv first: `source ../odoo-venv/bin/activate`. `odoo.conf` is local (gitignored) and sets
`without_demo = True`; tests need demo data, so use a separate test database with `--with-demo`.

```bash
# run the server
./odoo-bin -c odoo.conf

# install/update a module and run its tests (use a throwaway database)
./odoo-bin -c odoo.conf -d test_ai_home --with-demo -i ai_home --test-tags /ai_home --stop-after-init
./odoo-bin -c odoo.conf -d test_ai_home -u ai_home --test-tags /ai_home --stop-after-init

# one test class or method
./odoo-bin -c odoo.conf -d test_ai_home -u ai_home --test-tags /ai_home:TestHomeInsight --stop-after-init

# JS (hoot) tests: with the server running, open in a browser
#   http://localhost:8069/web/tests?debug=assets   (filter by the module, e.g. @ai_home)

# lint (config in ruff.toml)
ruff check addons/ai_home
ruff format --check addons/ai_home
```

## Known failing tests (not caused by recent work)

- `ai_home` `TestWorkDashboard.test_home_is_the_first_internal_root_app` (icon size `320` vs `50`)
- `ai_home` `TestWorkDashboard.test_website_home_menu_navigates_directly_to_home` (`#` vs `/odoo/home`)

## Plans and current work

- Execution plans: `docs/exec-plans/active/` (in progress), `docs/exec-plans/completed/` (done).
- Home insights (done 2026-11-06): `docs/exec-plans/completed/2026-11-05-home-insights.md`.
  Plan doc: https://claude.ai/artifact/TxCCU5LsvThdtqSegadC4f. Approved mocks: https://claude.ai/artifact/GbgaQoaMLF4eXQfTtFS49G
- Marketing: `docs/exec-plans/active/2026-10-23-intelligent-marketing-gap-analysis.md`,
  `docs/exec-plans/active/2026-10-25-marketing-roadmap.md`.
- Architecture decisions: `docs/design-decisions/`. Verified Odoo 20 facts: `docs/references/odoo20-verification.md`.
- Odoo's agent skills (review, security, guidelines) are in `skills/`.
