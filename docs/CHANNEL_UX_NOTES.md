# Channel UX — user requirements and lessons

Recorded from the user's channel-design requests on 2026-10-10. Read before
changing channel setup, forms, cards, lists or provider adapters.

## Scope and simplicity

- WhatsApp work (2026-10-11): create a separate `omni_whatsapp` addon. Do not
  edit `omni_channel` or `omni_telegram`, or change their behavior through
  inheritance, without first presenting a short clear explanation, concrete
  evidence, a UI mock and a diagram. Record the proposed boundary explicitly.
- Initial WhatsApp onboarding connects an existing Meta Cloud API account and
  provides a link for creating a new Meta app; do not build embedded signup first.
- By default report what is being implemented, the next task and the remaining
  work. State unfinished capabilities explicitly; do not stop after a foundation
  and let the user infer that the integration is complete.
- This is a multi-provider channel module, not a Telegram-only product.
- The catalog includes WhatsApp Business, Telegram, Slack, Discord, LinkedIn,
  Facebook, Instagram, X, TikTok, YouTube, Threads and Pinterest. A catalog entry
  does not establish that an adapter is installed or its capabilities work.
- Shared layout, progress, navigation and everyday actions belong in the shared
  channel experience. Providers supply only their applicable credentials,
  connection behavior and capabilities. Do not require Telegram bot tokens,
  numeric Telegram test IDs or Telegram sandbox actions for another provider.
- Verify installed adapter capabilities before displaying an enabled action.
  Explain an unavailable capability briefly; never imply unimplemented behavior.
- Simplicity: few fields, few buttons, short direct instructions. Avoid repeated
  explanations, technical tables on everyday cards, and steps inside steps.
- Credentials guidance must not mention the internal database name. Telegram
  tokens come from BotFather; avoid the ambiguous phrase “bot’s administrator”.
- Do not use the phrase “You’re right.” in replies to this user.
- When asked for a mock first, show a concrete mock before implementing it.

## Current approved presentation

- Connection choice uses Create new connection / Use existing connection radio
  buttons with `mb-3` below. Reused credentials must not be requested again.
- For a new Telegram connection, the secret is generated automatically when left
  blank. The user questioned the custom-secret input as unnecessary; automatic
  generation is the intended simple flow. Do not claim the input was removed
  unless the actual view has been changed and loaded.
- No duplicate central step number/title; the left navigation identifies steps.
- Channels filters: Communication teams, then Channel types.
- Cards: channel name at left, bot/account display immediately below when relevant.
  Channel-type tag at top-right, team tag below, then truthful readiness/connection
  status. Do not show Connected merely because setup progress is complete.
- One continuous progress bar, trailing `0/5`–`5/5`; no Setup label or duplicated
  progress wording, no extra margin above/below, no internal horizontal divider.
- No Runtime sender wording, sender/endpoint counts or Receiving messages wording
  on cards. Do not remove the underlying safety checks because their labels hide.
- Completed Telegram card: Edit test users bottom-left, Inbox immediately right,
  Settings bottom-right. Test IDs/configuration actions remain manager-only.
  Other providers need equivalent actions only where supported, with suitable names.
- Start setup / Continue setup remain bottom-right on incomplete cards. Card
  backgrounds remain non-opening; use native buttons, not click/CSS hacks.
- Compact completed-channel page: summary, inbox, settings and test-user editing.
  Retain infrastructure controls through the native administrator action menu.

## Avoid repeating implementation failures

- Verify checked-out Odoo 20 and bundled Owl 3 before implementing components.
  Use `props = useProps(...)`, never static props/defaultProps. Template access to
  component members uses `this`, e.g. `this.completed` and `this.segments`.
- Odoo view inheritance matches the first XPath result. A broad selector does not
  apply a modifier to every matched node; verify the actual combined view.
- Empty `t-else` on a kanban widget field becomes invalid generated JavaScript.
  Put the conditional directive on a `<t>` wrapper instead.
- XML/schema checks and template compilation do not establish successful mounting.
  Mount the actual component with bundled Owl, exercise updates, and check layout
  and accessibility. Browser tools are in test_card_compilation.cjs and
  test_setup_progress_browser.cjs; use the real checked-out compiler/runtime.
- Validate incomplete and complete states, manager/operator visibility, company/team
  boundaries and a non-Telegram provider path when shared behavior changes.
- Do not leave the old UI loaded after a change. Upgrade the affected local module,
  verify its combined views, and distinguish a required refresh/restart from a fix.
- Tests must not send real email or Telegram messages. Suppress signup invitations
  with the existing safe test-user helper, block mail transport in ad-hoc database
  checks, use fake Telegram transport, and roll back synthetic records. Database
  rollback cannot retract externally sent mail.
- Preserve approved policy/action boundaries, audit history and immutable retention
  versions. Never quietly enable business dispatch while simplifying setup.

## Template editor (2026-10-11)

- Use the approved email-template-style editor for every channel catalogue type.
- Keep optional header/footer/link-button fields collapsed until explicitly added.
- Show a record-based preview beside the content; no recipient or send button.
- All formats can be authored, but authoring never implies connector availability.
- WhatsApp template status remains “Not submitted” until real provider submission
  exists. Do not simulate provider approval in the installed UI.
- Use business-record choices and native record search; template authoring must
  not grant operators access to technical `ir.model` records.
