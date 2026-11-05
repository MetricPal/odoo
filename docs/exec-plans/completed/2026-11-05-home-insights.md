# 2026-11-05 Home insights

Status: complete (2026-11-06). Plan doc: https://claude.ai/artifact/TxCCU5LsvThdtqSegadC4f.
Approved mocks: https://claude.ai/artifact/GbgaQoaMLF4eXQfTtFS49G (boards Main, Manager, Insights, Dashboard,
DashOverview, DashContacts).

## Objective

Make Home useful: show what needs the user's attention across every app in 1.1, in one list, and give
administrators a full view of the system and of every insight Home raises.

## Scope

- Home's middle column is one list of decisions and insights, most urgent first, on the page background: no white
  card, no sections, no tabs, no chips (like the claude.ai app).
- Insights for CRM, Employees, Recruitment, Expenses, Inventory, Contacts, Invoicing, Sales, Purchase, eCommerce,
  Marketing (mass_mailing, mass_mailing_sms, every `*_marketing`), Time Off, Project, Events, Survey.
- Completeness ("Incomplete information") of records in every app, not only profiles.
- Mentions outside the chatter (activities, workflows, SMS, Omnichannel, social) notify the user; the same template
  on one day gives one notification with a count and one sample.
- System overview for administrators: card under "What just happened", a page with KPIs and telemetry and an Apps
  table; an Apps row opens that app's report (cards, charts, table; no side menu; back returns to the overview);
  "All insights" lists every insight.

## Non-scope

- Role templates and sensitive-field restrictions (`metric_access`): dropped.
- No change to who can see or approve records; insights respect each user's access.

## Affected modules

- `ai_home` (version 1.10)
- `metric_mention` (new)

## Design

- `ai.home.insight`: rules with measure `count`, `completeness` or `check`; audience group, required module,
  priority (act_soon, incomplete, going_well, system), tone, sentence / sentence_one, detail, button, action.
  Domains can use `uid`, `today`, `now`, `days_ago(n)`, `days_ahead(n)`.
- `ai.home.insight.field`: weighted fields for completeness (scores at most 1000 records per rule, cached 15
  minutes; Home shows only the three worst completeness rows).
- `ai.home.insight.snapshot`: daily value per user and rule, for "more than yesterday" and 30-day trends.
- Starter data: 19 count rules (`data/ai_home_insights.xml`), 17 completeness rules
  (`data/ai_home_completeness.xml`), 6 system checks for administrators (`data/ai_home_checks.xml`: failed emails,
  failing crons, unhealthy senders, AI engines, failed runs, users without 2FA). Records are `noupdate`.
- Front end: `streamList(attention, insights)` ranks overdue decisions, bad, other decisions, warn, info, good.
- `metric.mention.digest`: one row per user, channel, template (sha1 of normalised text) and day; SMS via a
  `mail.message` hook, activity notes via `mail.activity` create/write, Omnichannel and social via a 5-minute cron
  with a watermark.
- System overview (`/odoo/system-overview`), All insights (`/odoo/insights`) and app reports
  (`ai_home.insight_report` client action with `params.app`): administrators only.
- Request counter `ai.home.request.stat`: per hour and route (numbers become `:id`), counted per worker in memory in
  `ir.http` and written at most once a minute with its own cursor; durations in five buckets for p95; 5xx counted;
  rows older than 90 days removed by the autovacuum.

## Phases

1. Insight rules, 19 starter insights, one middle list.
2. Completeness, 17 starter rules.
3. System checks.
4. `metric_mention`.
5. System overview page; All insights and app reports; request counter.

## Verification

- Python tests: `ai_home/tests/test_home_insight.py`, `test_home_data.py`, `test_dashboard_*`;
  `metric_mention/tests/test_mentions.py`. JS: `ai_home/static/tests/dashboard.test.js`.
- Checked on a demo database with crm, sale_management, purchase, stock, hr_holidays, hr_expense, calendar,
  approval_center, social_home, ai_agent, metric_mention; screenshots of Home, System overview, All insights and
  the Contacts report.
- Two `ai_home` tests fail independently of this work (see `CLAUDE.md`).

## Known limitations and follow-up

- Starter records are `noupdate`: databases that installed an earlier version keep older sentences.
- Open: a "mention users" option on `workflow_center` message steps.
- Open questions: which starter insights to keep, list order, profile weights, job seekers, the mention day.
