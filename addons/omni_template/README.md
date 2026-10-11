# Omnichannel Templates

This is a shared feature addon, not a standalone app. Its launcher and navigation
menus are inactive. Other applications will expose the existing template actions
later. The editor and scoped rendering API remain available for that integration.

Choose a channel, business record type and content type. Write content, insert
record fields, select a sample record and save. Optional header/footer/button
fields expand only when added. Media rows can be reordered with the drag handle.

The Content tab contains the editor and a record-based preview. Options contains
team, company, content language and a suggested approval policy. Templates can be
duplicated, archived, searched and grouped by channel or team.

## Authoring formats

| Channel | Formats |
| --- | --- |
| WhatsApp | Reply; local WhatsApp template with category and language |
| Telegram | Message, photo, video, audio, document |
| Slack / Microsoft Teams | Message, card |
| Discord | Message, embed |
| LinkedIn | Post, carousel, public reply |
| Facebook | Post, photo, video, public reply |
| Instagram | Photo, carousel, reel, story, public reply, private reply |
| X / Threads | Post, photo, video, reply |
| TikTok | Video, photo post |
| YouTube | Video and title |
| Pinterest | Pin and title |

Teams appears when its channel catalogue entry is installed by `omni_teams`.
Authoring a format does **not** install a connector or enable provider execution.
Cards/embeds currently contain text and an optional link button; this is not an
arbitrary Block Kit or Adaptive Card JSON builder. Media preview lists ordered
files, not a provider-rendered player. Language is template metadata; there is no
automatic translation.

## Boundaries

Saving, previewing and duplicating never send, publish, register webhooks, submit
to Meta, create approvals or grant recipient consent. WhatsApp templates remain
local drafts, explicitly marked **Not submitted**. Provider moderation is not
represented by local ERP approval. This addon does not change connector code or
add template selection to existing sending forms.

`render_content(record_id)` returns a scoped, rendered copy and ordered media
references for future composers. A consumer must revalidate channel capability,
media, recipients, consent and its existing approval policy before executing.
Template approval type is a suggestion, never an override of channel policy.

Company/team access follows `omni.scope.mixin` and native `ir.access` rules.
Public/portal users have no access. Sample records and each related record retain
the caller's ACLs and must be shared or belong to the template company. No `sudo`
is used for content rendering. No technical-model metadata permission is granted.
Supported business record choices are contacts, leads, orders, invoices, tasks and
helpdesk tickets when those applications are installed.

Field syntax uses Odoo's native inline parser: `{{ object.name }}`,
`{{ object.email ||| fallback }}` and `{{ company.name }}`. Only readable scalar
fields and bounded many-to-one paths through supported business models are
accepted. Method calls, `env`, arbitrary Python, binary fields and private or
group-restricted fields are rejected. Preview HTML escapes all content before
applying a small, channel-specific bold/italic subset. Buttons are inert.

## Verification

```sh
.venv/bin/python addons/omni_template/tools/check_install.py
OMNI_NODE_MODULES=/path/to/node_modules node addons/omni_template/tools/test_ui.cjs
```

Set `OMNI_NODE_MODULES` and optionally `OMNI_NODE` when running `check_install.py`
to include a full browser test. It starts a temporary Odoo server on localhost:8089
with cron disabled and synthetic identities in a disposable database. Both server
and database are removed afterward. External requests are blocked during the
installation and native ORM tests; no connector is called by template methods.

Coverage: install/upgrade/combined views; every channel-format native form;
rendering, escaping and no-send behavior; code/field/link rejection; company/team,
portal and metadata permission isolation; ordered media and copies; optional
field removal; actual Owl 3 widget; actual Odoo form, field picker and responsive
editor.
