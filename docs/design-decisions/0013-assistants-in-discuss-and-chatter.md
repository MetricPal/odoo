# ADR 0013: Assistants in Discuss and the chatter; OdooBot stays the system voice

Date: 2026-11-08. Status: proposed, for owner review (the mocks are approved: AI Agent control panel canvas boards 10 to 12,
https://claude.ai/artifact/9Uw7Mzz6KG8FXCZ3m6mqtd). Implementation planned in
`docs/exec-plans/active/2026-11-08-assistants-in-discuss.md`. Builds on ADR 0012.

## Context

People reach agents only from Home and the AI Agent conversations. The owner wants them where people already talk:
Discuss (the page and the chat windows of the messaging menu, where OdooBot is) and the chatter of records.
OdooBot is `base.partner_root`, whose user is `base.user_root`, the superuser (`SUPERUSER_ID = 1`); `mail_bot`
gives it a scripted onboarding chat; our modules already use it as the system identity (MCP endpoint, crons,
mention digests).

## Decision

1. **OdooBot is not the assistant.** It stays the system voice; `mail_bot` is not overridden. An AI answer never
   comes from the superuser, and system messages stay distinguishable from AI answers.
2. **Each agent is its own chat partner.** An agent gets its own `res.partner` (name, avatar), shown with an
   **AI** label. It is not a login user. Chatting with it is a normal Discuss direct chat
   (approved board 10 and 12): the Discuss page and the messaging-menu chat window, with an **Assistants** filter
   next to All, Unread and Group. Paused agents are listed greyed out. Only people in the agent's audience see or
   open its chat.
3. **Answers go through the existing run path.** A message in an assistant chat queues an `ai.agent.run` for the
   person who wrote it (assistant and person rights, ADR 0012), and the answer is posted in the chat by the agent's
   partner, with "Used: …" and any proposal (Approval Center) linked. Nothing is changed without approval.
4. **Chatter: an Assistants composer, internal notes only** (approved board 11). Next to Log note, an
   **Assistants** button opens a composer like Send message: **To:** the assistant (a picker of the agents that may
   look at this kind of record), the question box, **Send**. The question and the answer are internal notes on the
   record ("on behalf of" the person); nothing is ever emailed to followers. The button shows only to people with
   at least one such agent.
5. **Not now:** shared channels (an answer would have to fit what every member may see), @ mentions of assistants
   in Send message, and assistant chats with portal or public users. The department assistant users (ADR 0012) are
   hidden from mention suggestions: they are identities agents act as, not chat partners.

6. **Module.** The Discuss and chatter parts live in a new module, `ai_discuss` (depends on `ai_agent` and `mail`,
   auto-installed), like `workflow_ai` and `omni_ai`: `ai_agent` stays the control panel and the chat surfaces can
   be removed on their own. The Recruitment data scope belongs to `ai_agent`.

## Alternatives considered

- **OdooBot as the assistant:** rejected; it is the superuser, it is one identity for system and AI messages, and
  it is one partner for many agents with different audiences. Overriding `mail.bot` also fights core updates.
- **One chat per department assistant user, agent chosen inside the chat:** fewer entries, but an extra step and a
  chat whose audience is not one agent's audience.
- **@ mention in Log note:** works with standard Odoo but is not discoverable; replaced by the Assistants button.

## Consequences

- One partner per agent; archiving or pausing the agent archives or greys out its chat.
- The chatter Assistants composer is new UI in every form with a chatter; it is hidden when no agent fits.
- Agents need read access to the record's model for chatter questions; Recruitment and other personal-data
  models are added to the agent data scope only when switched on per agent.
