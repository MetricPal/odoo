# WhatsApp v1 offline verification — 2026-10-11

Verified scope: existing Cloud API account setup, signed private-text intake into
the native inbox, and one manager-confirmed fixed setup test. Normal business
dispatch remains disabled and is not implemented by this version.

## Results

| Check | Result |
| --- | --- |
| Protocol, Graph transport, diagnostic and encrypted vault unit tests | 44 passed |
| Existing Omni-Channel / Telegram view regressions | 6 + 4 passed |
| Actual Owl Credentials and receiving components; inherited setup template | Passed |
| Native Form default/onchange/create and final receipt save | Passed |
| Manager/operator/portal/team/company and forged-field/default guards | Passed |
| Scoped GET handshake and signed POST intake; native inbox and deduplication | Passed |
| Duplicate/blocked/stale tester guards and receipt-controlled completion | Passed |
| Clean installation without Telegram and repeated upgrade | Passed |
| Two real concurrent sessions, fake send transport | One send; second blocked |
| Committed pending claim visible before fake send | Passed |
| Committed uncertain result survives caller rollback and blocks retry | Passed |
| Configuration changes and withdrawn receipt invalidate completion | Passed |
| Combined native view validation, Python compilation and whitespace check | Passed |
| Source changes to `omni_channel` or `omni_telegram` | None |

The concurrency test deliberately permits Odoo's serialization conflict for the
losing session. It verifies exactly one fake provider invocation; it does not
treat a database conflict as a successful second send. All disposable databases
and filestores were removed. Checks in the user's development database rolled
back their fixtures. No real Meta request, message or email was sent.

The review fixed two defects: rejecting a new form's unchecked receipt Boolean,
and translating the result notification after closing its local diagnostic cursor
when the caller context lacked a language.

## Repeatable commands

```sh
.venv/bin/python -m unittest discover -s addons/omni_whatsapp/tests -v
.venv/bin/python -m unittest discover -s addons/omni_channel/tests -p test_channel_views.py
.venv/bin/python -m unittest discover -s addons/omni_telegram/tests -p test_connection_view.py
.venv/bin/python addons/omni_whatsapp/tools/check_clean_install.py
```

The two browser tools in `tools/` require `OMNI_NODE_MODULES` pointing to a local
Playwright installation. The installed development-database checker is executed
in an Odoo shell, remains rollback-only, and blocks external calls and emails.

## Unverified and unimplemented

No WhatsApp Business account was available, so real credentials, public tunnel,
Meta subscription, sending permission and end-to-end delivery remain unverified.
Actual component checks and native Form checks do not substitute for a complete
logged-in browser tour of every wizard screen. Normal business replies,
templates/media, shared/automatic callback registration and interrupted-attempt
reconciliation are not implemented. Restart Odoo before using the Python fixes.

This closes the offline verification of the implemented v1 scope. It is not a
claim that a full two-way WhatsApp messaging application is production-complete.
