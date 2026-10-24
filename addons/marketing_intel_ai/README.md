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
