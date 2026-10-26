# Marketing: assistant chat

Marketing › Assistant › **Ask the assistant** (also on the control panel). Write what you want; the assistant
shows exactly what it will do (*I will …*); nothing changes until you click **Do it**.

What it can do, always with your own access rights:

| Say for example | It does |
|---|---|
| create campaign "Black Friday" for metric.io with email and social from 20 Nov to 30 Nov, budget 500, let the AI write it | creates the campaign (AI assistant writes it and sends it for review if asked) |
| change … / anything the AI agent understands | changes dates, channels, budget, message, audience — only before the review |
| duplicate Clinic open day starting 1 Dec | copies channels, texts and tasks; the copy needs its own review |
| send Clinic open day for review | the usual one campaign review (same approvers, same checks) |
| pause Clinic open day | takes a campaign out of review (back to Content) |
| cancel campaign … | cancels it; what was sent stays sent |
| how is the open day campaign doing? · report all | answers straight away with status, channels and results |
| pause workflow Comment INFO · resume workflow … · ask approval for workflow … | the workflow's own actions (resume only if unchanged since approval) |

Simple instructions like these are understood directly (no AI call). Anything else goes to your AI agent
(AI Agent app; the brand's agent if set): the agent has no tools and only returns one JSON action, which is
validated against existing campaigns, workflows, brands and channels before it is proposed. Each request is
kept in Assistant › History with who asked, how it was understood, the proposal and the result; changed
records also get a note in their chatter.
