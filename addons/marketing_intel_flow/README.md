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
