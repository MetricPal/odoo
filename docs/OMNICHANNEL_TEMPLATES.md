# Omnichannel templates

The approved editor is implemented in the separate `omni_template` addon. It uses
native Odoo forms, list/search, record search, inline placeholder parsing and
TextField editing, with a compact toolbar and responsive preview panel. The
addon does not modify `omni_channel`, `omni_telegram` or provider execution.

Flow: choose channel → choose business record/content → write → preview → save.
Templates are reusable authoring records, not executable commands. The scoped
rendering API returns a copy; any future sending integration must freeze that
copy under its existing human-approved execution policy. Provider submission,
provider approval and ERP approval remain separate concerns.

See `addons/omni_template/README.md` for formats, access boundaries, current limits
and reproducible tests. The UI prototype remains the design reference; production
controls must report actual capabilities rather than simulate Meta submission.

User navigation decision: templates and Social are shared feature addons with
`application=False` and inactive standalone menus. Their actions and views are
retained for future host-application integration. No replacement app is added.
