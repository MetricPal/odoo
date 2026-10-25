# Marketing Intelligence: campaign plans

Turns a **chosen** campaign option into a plan with linked drafts in each
marketing app. Marketing Intelligence never sends, publishes or spends.

1. On a campaign option, click **Choose this option**, then **Create campaign
   plan**. Dates come from the option's duration; one line per channel.
2. **Prepare drafts** creates one UTM tracking campaign and, per channel, a
   draft in the app that owns it, with your own permissions:

   | Channel | Draft created in |
   |---------|------------------|
   | Social | Social Marketing campaign (`omni.social.campaign`) |
   | Messaging | Messaging Marketing mailing (`mm.mailing`) |
   | Email | Email Marketing mailing (`mailing.mailing`, email) |
   | SMS | SMS Marketing mailing (`mailing.mailing`, SMS) |
   | Virtual / physical event | Event (`event.event`) |
   | Content, ads, partnership | To-do activity on the plan |

   An app that is not installed, or that you have no rights in, leaves a note
   on the line instead of an error. Preparing again only fills missing lines.
3. Each draft keeps its own approval and sending rules in its app. The plan
   shows each draft's status there; **Open** jumps to it.
4. **Campaign plans** opens as a calendar. A plan warns when another active
   plan of the same brand overlaps on the same channels (contact fatigue).

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

