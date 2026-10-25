# Marketing Intelligence: AI analysis

Adds an AI-written analysis to each research run of `marketing_intel`:

- a summary and a SWOT,
- 1–4 campaign options (channel mix, audience, budget, duration, KPIs,
  expected result, confidence, linked evidence),
- risks (category, likelihood × impact, mitigation, linked option).

## How it works

1. On the brand, choose the **AI agent** (tab *AI analysis*). Optionally tick
   **Analyse every research run** and choose **Ask AI as** (a person with
   Marketing Intelligence and AI Agent access; the request uses their quota).
2. On a research run, click **Analyse with AI** (or let the schedule do it).
3. The agent receives the brand profile, goals, approved competitors and the
   run's findings (at most ~11,500 characters, marked as untrusted data) and
   must answer with one JSON object (`models/schema.py`).
4. The answer is validated: types, sizes, known channels and categories,
   at most 4 options and 10 risks. Evidence must be findings of the same run
   (others are dropped). An invalid answer stores nothing and leaves a note.
5. Valid answers replace only AI options still waiting for a decision and open
   AI risks; anything people wrote or decided is kept. Automatic checks then
   flag options above the monthly budget and lower the confidence of options
   without evidence. The brief (Report Studio) is rebuilt.

The agent has no tools. Choosing an option only marks it; drafts in each app
come in phase 3 and still go through their own approvals.

## Campaign autopilot

On a campaign, choose **Who does the work: AI assistant** (or click **✨ Let AI write it**). The AI
agent of the brand (or the only agent available to you):

1. fills the key message, audience and KPIs when they are empty;
2. writes every channel in its own format: email subject and body, SMS (max 160 characters),
   Messaging text (max 900), social post (max 2000), event title and description;
3. prepares the drafts with your permissions, fills them and sends the campaign for review.

The answer is strict JSON; anything invalid or too long is rejected as a whole and the campaign keeps
a note. The AI never approves: the campaign review releases it. When the campaign is done, the AI
writes *What we learned*, which feeds the next suggestions.
