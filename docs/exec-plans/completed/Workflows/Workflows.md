- **Workflows home:** every workflow is now explained as "When → If → Do".
  - **Describe it:** the example description is an automation (overdue invoice reminders that escalate), with suggestion buttons for others.
  - **Templates:** filter by kind: reminders, data updates, creating records, scheduled jobs, integrations and approvals. Examples include overdue invoices, new lead assignment, employee onboarding, a daily low-stock check, sending orders to another system and a won deal starting a project. The two approval templates are still there.
  - **Building blocks:** a side panel lists what you can use:
    - **Triggers:** created, changed, stage or status, button, date field, schedule, incoming webhook.
    - **Actions:** update record, create record, activity, add followers, email or chat, outgoing webhook, Python code.
    - **Logic:** condition, branch, wait, for each record.
    - **Optional:** approval.
- **Builder:** five working examples. Only one is a pure approval flow:
  - **Invoice reminders:** a date trigger, an email, a wait, then a "Paid yet?" branch leading to a thank-you or to a call and an alert to the accountant.
  - **New leads:** assign a salesperson, send a WhatsApp welcome, book a call, then check whether it was done.
  - **Onboarding:** no branch at all. It creates tasks, asks IT for a laptop, calls a webhook, waits until the first day and sends a welcome email.
  - **Low stock:** a daily schedule creates a draft request for quotation. Only ones above a limit go through an approval step.
  - **PO approval:** the original approval flow.

  The step menu is grouped into Actions, Logic and Optional (Approval), and new steps go after the one you've selected. Action steps also let you choose what happens if they fail.
- **Run history (new):** I added this screen because automations need monitoring. You can filter runs as Running, Waiting, Failed or Done and see each run step by step. A failed step shows its error, for example a webhook that returned 503, with buttons to retry, skip or stop.
- **Approval step and My approvals:** unchanged, now labelled optional and placed last on the canvas.