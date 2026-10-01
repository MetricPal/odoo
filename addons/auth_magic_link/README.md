# Odoo 20 Community — Configurable Magic Link Authentication

This module provides four administrator-controlled login modes:

- **Username & Password** — Odoo's native local login.
- **Magic Link** — passwordless email login, with configured OAuth providers still available.
- **Password or Magic Link** — both local methods are available.
- **OAuth only** — local password and magic-link forms are hidden.

The administrator selects the global mode under **Settings → Authentication**.
Login, signup, password reset, TOTP, and other authentication forms are rendered
by Odoo's standalone web login layout, not inside the Website header, footer, or
page structure.

## Safety gates

Magic Link modes can only be saved when the System Administrator has a valid
email address and an active outgoing mail server exists. OAuth-only mode can
only be saved when that administrator is linked to an enabled OAuth provider.

If a selected method later becomes unsafe because the email server, admin
email, or OAuth provider is removed, the effective login page falls back to
Username & Password to prevent database lockout.

## Magic Link flow

1. The user enters an email address.
2. The server creates a cryptographically random one-time token.
3. Only the SHA-256 hash is stored in `auth.magic.link`.
4. The raw token is sent by email and is never persisted.
5. The token expires after the configured time (default: 10 minutes).
6. Token consumption uses an atomic database update, so only one request wins.
7. Issuing a new token invalidates older outstanding links for the user.
8. Scheduled cleanup removes expired and used records every 15 minutes.

## Security notes

- Unknown and ambiguous emails receive the same generic response as known users.
- Password and magic-link restrictions are enforced server-side, not only hidden in the UI.
- API/non-interactive password authentication is unchanged.
- Redirects are restricted to local paths (`/…`).
- Only system administrators have model access to stored token metadata.
- Authentication continues through Odoo's standard session and MFA pipeline.

## Installation

1. Add `auth_magic_link` to the configured addons path.
2. Update the Apps list and install **Magic Link Authentication**.
3. Configure an outgoing mail server and the System Administrator email.
4. Configure OAuth providers if OAuth login will be offered.
5. Open Settings → Authentication and select the desired mode.
6. Set Magic Link validity between 1 and 60 minutes.

After Python changes, restart all Odoo workers before testing.

## Verification

Automated tests cover hashed and expired tokens, one-time consumption,
authentication replay rejection, lockout fallback, settings validation, model
access, login-page rendering, and unknown-email request handling.

The Odoo 20 API verification record is in
`docs/references/odoo20-verification.md`.
