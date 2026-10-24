# Marketing Intelligence (phase 1)

Recurring, approved research with evidence, per the
[gap analysis](../../docs/exec-plans/active/2026-10-23-intelligent-marketing-gap-analysis.md).

1. **Setup > Brands & goals**: what you sell, to whom, why customers choose
   you, voice, markets, monthly budget, goals (target vs current), and how often
   to research (days, weekly by default).
2. **Competitors** and **Sources** (web page or RSS/Atom feed, HTTPS only) are
   proposed by any user and **approved by an administrator** with a written
   reason ("public page, no login, terms allow reading"). Changing a source's
   address sends it back for approval. Paused or rejected sources are skipped.
3. **Research** runs on schedule (hourly check, per-brand interval) or with
   *Run research now* / *Collect now*. The collector respects robots.txt, uses
   no login or cookies, refuses redirects to other sites, and caps size (2 MB)
   and time.
4. **Evidence**: every collection is a dated snapshot (address, HTTP status,
   SHA-256, extracted text). The next collection is compared with it.
5. **Findings**: first evidence, page changed (with added/removed lines), new
   feed item, or could not collect (with the reason). Mark reviewed or dismiss.
6. **Brief**: each run creates a shared Report Studio report (changes, errors,
   summary, findings table) that exports to PDF, Excel, PowerPoint or Word.

Not yet (phase 2+): AI-written analysis and campaign options, SWOT/risk
register, Approval Center integration for source approval, company record
rules on findings/evidence, more collectors (reviews, social, trends, ads).

## Phase 2: analysis, options and risks

Each research run has tabs for **Analysis & SWOT**, **Campaign options** and
**Risks**. People can fill them in by hand; `marketing_intel_ai` (installed
automatically with AI Agent) asks an AI agent for them. **Refresh brief**
rebuilds the Report Studio brief with these sections. Automatic checks flag
options above the monthly budget and lower the confidence of options without
evidence. Menus: *Campaign options* (choose / reject) and *Risk register*.
Company rules now apply to every Marketing Intelligence record.

Workflows has a built-in template **Market brief review**: when a brief is
ready and changes were found, it schedules a review activity and posts the
brief to followers.

