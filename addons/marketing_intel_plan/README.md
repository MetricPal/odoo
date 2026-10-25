# Marketing: campaigns

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
- **Next step** is shown on every campaign (who it waits for, or that it runs by itself). **My to-dos**
  is personal: campaigns where *you* must approve, write or fix something, with what to do.
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

