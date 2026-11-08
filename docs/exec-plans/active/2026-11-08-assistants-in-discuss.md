# 2026-11-08 Assistants in Discuss and the chatter

Status: phases 1 and 2 done 2026-11-08 (`ai_discuss` 20.0.1.0.0); phases 3 and 4 not started. ADR: `docs/design-decisions/0013-assistants-in-discuss-and-chatter.md`.
Mocks: https://claude.ai/artifact/9Uw7Mzz6KG8FXCZ3m6mqtd boards 10 (Discuss page), 11 (chatter Assistants
button), 12 (messaging menu and chat window). Build only what they show.

## Objective

People ask the agents they may use from Discuss (page and chat windows) and from a record's chatter, as easily as
they chat with a colleague, without OdooBot changing and without anything being emailed or written without
approval.

## Modules

- `ai_discuss` (new, auto-installed with `ai_agent` and `mail`): agent chat partners, the Discuss chat, the chatter
  Assistants composer (phases 1 to 3).
- `ai_agent`: the Recruitment data scope (phase 4); its model list already skips apps that are not installed.

## Phases

1. **Agent chat partner.** `ai.agent.partner_id` (created and kept in sync with the agent's name, archived like
   OdooBot's partner, so it stays out of Contacts, pickers and @ suggestions); department assistant users hidden
   from mention suggestions too.
   **Done 2026-11-08** (`ai_discuss` 20.0.1.0.0): partner made with the agent (and for existing agents at install),
   follows its name and company, removed with an agent deleted unused; `res.partner.ai_agent_partner` marks it;
   AI assistant users left out of @ suggestions.
2. **Discuss chat.** Opening an assistant creates or reuses the person's direct chat with the agent's partner,
   only for people in the audience. A message there queues a run (`ai.agent.run`, person and assistant rights);
   the answer, "Used: …" and proposal links are posted by the agent's partner; "is answering…" and Stop. Assistants
   filter (Discuss page and messaging menu), AI label, paused agents greyed out, What it can do (Home's window).
   **Done 2026-11-08**: each person in an agent's audience gets a chat with it at sign-in (answering and paused
   agents, made once like OdooBot's); a message there is one run as that person (origin: the chat), follow-ups
   continue the same conversation; the answer, or the reason there is none, is posted by the agent's partner,
   with proposals listed as "Proposed: … · Waiting for approval · Open request"; Odoo's "is typing…" shows while
   the run works. Assistants filter (server and client), AI label in the list and on messages, list preview
   "department · description" (or "· Paused", greyed out), the chat's start line.
   Not done from board 10: "What it can do" link, "Stop", "Used: …" (runs do not record what they used), and
   "is answering…" (Odoo's own "is typing…" is used).
3. **Chatter Assistants composer.** Template extension of `mail.Chatter`: Assistants button after Log note, a
   composer with To: (agent picker filtered by the record's model in the agent's data scope), the box with the
   placeholder "Ask <agent> about this <record>…", Send, paperclip and expand. Question and answer posted as notes.
4. **Recruitment data scope** (needed for the approved example): `hr.applicant` and `hr.job` allowed in agent data
   access when the Recruitment app is installed, off by default.

## Verification

- Python: chat only for the audience; a message queues a run as the person; the answer is a message of the agent's
  partner; chatter question and answer are notes (`subtype mail.mt_note`), never emailed; Send message and @ do not
  offer assistants; paused and archived agents.
- JS (hoot): Assistants filter, AI label, chatter button visibility and composer.
- Browser check of boards 10 to 12 on a test database.

## Risks and open points

- Discuss in Odoo 20 lists chats by partner; a partner without a user may need small patches (presence, avatar,
  "start of your direct chat"). Check before phase 2.
- Long answers: Discuss waits for the run like Home does (poll), and a failed run posts a short error note.
