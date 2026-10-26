# Marketing: workflows

"When this happens → do that", built from two cards and approved once.

**When** (the trigger)
- someone comments on a post (optionally containing a keyword, optionally only on one campaign's posts);
- someone sends a private message on the brand's social pages (optional keyword);
- someone registers for the campaign's event;
- someone clicks a link in the campaign's email;
- a new lead comes from the campaign.

**Then** (steps, in order)
- send a WhatsApp / Telegram message (`{first_name}` and `{name}` are filled in);
- add them to a Messaging list;
- create a lead in CRM;
- create a to-do for the owner.

**Approved once, then automatic.** *Ask for approval* freezes the trigger, the exact texts and the limits.
Workflows that send messages use the sending channel's own message approval type (its approvers are what
Omnichannel checks for every message); other workflows use the company's *Marketing campaign* type. Once
approved, the workflow reads new events every 5 minutes, only events after it started, and:
- handles each person once (unless *Once per person* is off);
- sends only to known contacts (social handle linked on the contact, Messaging contact with an opt-in on
  that channel), at most *Messages per person per day* across all workflows;
- logs every run with what was done or why it was skipped (no opt-in, unknown person, daily limit).

Messages are queued through Omnichannel with the workflow's approval as evidence (`_approval_targets_command`);
the dispatch worker re-checks the approval, the channel and the person's opt-in right before sending. Any
change to an approved workflow pauses it until it is approved again; queued messages of a changed workflow
lose their evidence and are not sent.

**Limit:** social platforms do not tell apps who *liked* a post (only how many). The equivalent that works
is "comment a keyword to get a message", which the first recipe does.

Recipes: Comment a keyword → WhatsApp link · Private message → lead and to-do · Event registration →
WhatsApp thank-you · Email click → lead for sales.


**Recipes** (Workflows › Recipes) are ready-made workflows to start from: four are shipped, and a marketing
manager adds more with **Save as recipe** on a working workflow (saving again updates that recipe; social pages,
sending channel, lists, campaign and limits are not kept). Managers edit recipes in a normal list and form
(trigger, keyword, step lines), reorder and archive them; everyone else uses them. **Use this recipe** creates a
draft workflow for the brand in view, or asks which brand when there are several; it still needs its approval.

**Paths (split).** Add a **Split the audience** step and give the next steps a path (Path A / Path B; name them,
e.g. High intent / Low intent). The split is decided by the AI agent (it reads what the person wrote and records
its reason on the run; an unusable answer goes to Path B), by words in what they wrote, or by the lead score.
The AI only sorts people; it never writes or sends. **Someone submits a form** watches website contact forms
(leads with the Website medium, optionally for one campaign) or newsletter sign-ups. **Send an email** and **Send
an SMS** skip unsubscribed and opted-out people and count towards the daily limit. Workflows without WhatsApp or
Telegram messages are approved with the approval type **Marketing workflow**. Recipe: *Form submitted → AI split
→ email or SMS*.

