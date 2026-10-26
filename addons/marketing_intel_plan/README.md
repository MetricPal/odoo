# Marketing: campaigns

**Control panel.** *Marketing* opens on one screen: key numbers with 8-week trends (messages sent, link
clicks, leads, won revenue, budget this month, goals on track), a timeline of upcoming and recent events
(sends, posts, events, reviews, campaign starts/ends, next runs of repeating campaigns, workflow runs; repeating
items marked), every running campaign with a coloured progress bar per channel, workflows with today's runs,
*For you* (your approvals, writing and fixes) and alerts (failed channels, overspend, goals behind). A brand
selector (grouped by company or client) filters everything.

**Customise the panel.** *Customise* shows each block with move up/down, half/full width and remove, and
*Add a block* offers the panel's other blocks (team workload and open requests come with Work management) and
any box from a Report Studio report you can read (numbers, charts as bars, tables, lists). *Save as my view*
keeps it for you; a marketing manager can *Save for a role* (marketer, advisor, manager). The view selector
switches between your view and the role views; without a view of your own you get your role's (manager if you
manage marketing, advisor if you work on client brands, marketer otherwise).

**Portfolio.** Marketing › Portfolio compares every brand for this month, quarter or year: budget,
spend (entered on each campaign's *Spend* tab), planned budgets, leads, revenue, revenue per spend,
campaigns, goals and a health badge with its reasons; grouped by company or client with totals. A
timeline shows all campaigns on one axis (clashes outlined, next runs of repeating campaigns hatched).
**Target quarter** on each campaign (e.g. "2026 Q4") is filled in from the start date and can be changed;
campaigns filter by last / this / next quarter and group by quarter, with budget, leads and revenue totals in
the list and pivot.

**Reuse.** *Duplicate & edit* copies a campaign with its channels and texts (new drafts, new review). *Save as
template* keeps it under Campaigns › Templates; *Use this template* starts a new one. *Repeat* every week or
month: a new copy is created three days before each run and sent for the one-click review (the AI assistant
rewrites the text when it does the work).

A campaign runs on any of the company's channels (Social, Messaging, Email, SMS, Events, plus to-dos
for content, ads and partnerships) and moves through one status line:

| Status | Meaning | Who acts |
|--------|---------|----------|
| Brief | Name, brand, goal, channels, dates, budget, message | Owner, or the AI assistant |
| Content | One draft per channel in its own app is being written | Owner, or the AI assistant |
| Review | One review for the whole campaign | Approver(s) |
| Scheduled | Approved; Email/SMS queued for the start day (09:00 owner's time), events published | Nobody |
| Live | At least one channel is sent or published | Nobody |
| Done | Closed automatically after the end date (or by hand); the AI writes what we learned | Nobody |

**Who does the work:** *Me* (you write each draft) or *AI assistant* (`marketing_intel_ai`: it fills
the brief, writes every channel and sends the campaign for review by itself).

**One review.** *Send for review* is all or nothing: it creates any missing draft and checks every channel
(lists, pages, sender, subject, text). If anything is missing, nothing is submitted, the lines show
**Needs fixing** with what to do, and a message lists the problems. Then:
- Messaging and Social drafts go to their own approvals (assigned approvers, frozen content);
- an Approval Center request of type **Marketing campaign** is opened for the campaign; it is the gate
  for Email, SMS and Events, which have no approval of their own.
The approver opens the campaign, reads every channel on the **Review** tab and clicks **Approve
campaign**: each request waiting for them is approved through its own app's checks, then the campaign
request runs `action_release` as the requester. **Refuse** sends the campaign back to Content with a
to-do for the owner. Set the approvers in Approvals › Configuration › *Marketing campaign* (each
company of a group gets its own copy on first use).

**Tracking.**
- The campaign stays in Brief, Content or Review until it is approved, whatever a channel app shows; a
  channel sent from its own app before the review is flagged on its line.
- Each channel line has one status: Not started, AI is writing, Being written, **Needs fixing** (a setup
  problem: missing pages, lists, channel...), Waiting for approval, Approved, Scheduled, Sent, **Failed**
  (sent to nobody or stopped in its app), To-do, Done; and a plain **Next step** saying what to do.
- *Channels sent* shows channels out of all channels (e.g. 1 / 4) next to the campaign day (Day 3 of 30).
- **Results** lists each channel's numbers from its app (audience, sent, delivered, opened, clicked,
  replies, not delivered; likes and comments for Social; registrations and attendance for Events) plus
  campaign totals and business results (leads, won deals, revenue).
- **Next step** is shown on every campaign (who it waits for, or that it runs by itself). When the owner must
  act, the step is an Odoo **activity** for the owner (Activities menu in the top bar, the campaign's chatter,
  "Your action needed" on the control panel); it is marked done by itself when the step is done. Approvals come
  as Approval Center activities; on the control panel they open the campaign, so one review covers it all.
- **Menus**: Marketing opens on the control panel (with a Portfolio button); campaign results are the pivot
  view of Campaigns; Goals are under Campaigns.
- An hourly job reads statuses and results back from the apps and closes finished campaigns.

Reviewers see each draft's text on the campaign even without rights in that app; opening the draft
itself still needs the app's rights.

## Brand accounts

Drafts take the brand's own accounts from Brand › Settings › Channels & accounts: Social pages for
the social campaign, the Messaging channel and its matching lists, the Email/SMS mailing lists and
the email sender. When the company has several brands and one is missing, the draft is not created
and its line says what to set up; it never uses another brand's account. A company with a single
brand falls back to the apps' defaults.

## Results and learning

The **Results** tab shows what each plan achieved, read back from the apps:
messages sent (Email, SMS, Messaging drafts), link clicks (tracked links of
the plan's UTM campaign), leads and won deals (CRM, by campaign), revenue
(confirmed sales by campaign, or won deals' expected revenue) and event
registrations. Add **targets** (metric + number) to see progress, and write
**What we learned**. Numbers refresh daily, on **Refresh results** and when
the plan is marked done. The pivot view compares plans.

The next AI analysis of the brand (marketing_intel_ai) receives the five
latest running or finished plans: channels, budget, targets vs actual and
lessons, so its options build on what worked.

Counts are aggregated with elevated rights (a plan owner sees totals even
without CRM or Sales access); no individual records are shown.

**Campaign list and form in Odoo's layout.** The campaign list has a summary strip above it, like Expenses and
Sales: campaigns per stage with arrows (Brief & content › Waiting approval › Scheduled › Running › Done; counts
ignore stage filters) and tiles for To do by you, Budget this quarter and Your activities; clicking one filters
the list. Columns: Campaign, Brand, Stage, Owner, Budget (total), Target quarter, Ends, Activities. The form keeps
its buttons and status bar in the header; smart buttons show Budget (and spend), Timeline, Channels and Approvals
(approved / total); tabs are Overview, Market research, Design, Approvals, Campaign, Execution, Report. The gear
menu has Print › Campaign report (PDF), Duplicate & edit and Save as template.

