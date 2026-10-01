# Odoo 20 verification: auth_magic_link

Verified against the Odoo 20 Community source in this repository before adapting the Odoo 19 `auth_email_link` reference.

## Verified APIs and conventions

- `ir.config_parameter` uses typed `get_str`, `get_int`, `set_str`, and `set_int` methods (`odoo/addons/base/models/ir_config_parameter.py`). The Odoo 19 `get_param`/`set_param` calls are not valid.
- `res.config.settings` persists `config_parameter` fields with the typed setters (`odoo/addons/base/models/res_config.py`).
- Authentication credentials flow through `res.users.authenticate()` and `_check_credentials()`, returning `uid`, `auth_method`, and `mfa` (`odoo/addons/base/models/res_users.py`).
- HTTP session authentication requires a `login` key before finalizing the session (`odoo/http/session.py`).
- Website-backed login routes require `website=True` and `auth="public"` to render the website-inherited login layout (`addons/website/controllers/main.py`).
- Odoo 20 access CSV files target `ir.access` and use `model_id`, `group_id/id`, `operation`, and `domain` (`addons/*/security/ir.access.csv`).
- SQL constraints use `models.Constraint`.
- OAuth readiness is represented by an enabled `auth.oauth.provider` linked through `res.users.oauth_provider_id` with a non-empty `oauth_uid` (`addons/auth_oauth`).
- Active outbound servers are `ir.mail_server` records with `active=True` (`odoo/addons/base/models/ir_mail_server.py`).

## Adaptation decisions

- Keep `auth_magic_link` as the module boundary instead of copying the Odoo 19 module wholesale.
- Support Password, Magic Link, Both, and OAuth-only modes.
- Fall back effectively to Password if a configured passwordless mode becomes unsafe, preventing administrator lockout.
- Validate settings before saving a passwordless mode.
- Keep raw tokens out of the database and consume them with an atomic SQL update.
- Preserve Odoo's normal authentication and MFA pipeline.
- Add model/security tests and HTTP rendering/request tests.

## Branding mail rendering

- Odoo 20 renders the password-reset QWeb body first, then wraps it with
  `mail.mail_notification_layout` in
  `auth_signup.models.res_users._action_reset_password()`.
- Odoo 20 Binary/Image fields expose `BinaryValue` objects; raw image bytes
  are read from `.content`. XML file data uses `type="bytes"`.
- The backend web client receives authenticated-user metadata from
  `ir.http.session_info()`. Branding extends that payload with the current
  user's email for the profile header instead of treating the login as email.

## Unavailable referenced documentation

`AGENTS.md` references project documents under `docs/` that were not present when this verification was performed. This note records the source-level verification required by the available local research skill.
