# Verification — 2026-10-11

- 19 pure tests passed, including real synthetic RSA signatures, tamper detection,
  wrong issuer/audience/tenant/bot/channel, expiry/future/NaN, algorithm confusion,
  missing Teams endorsement, unknown keys, untrusted discovery URL, unsafe service
  hosts/paths, duplicate JSON keys, text/attachment filtering and encrypted scope.
- Fixed tenant token endpoint and reply outcome classification passed; token
  failures do not send activities and activity timeouts never retry.
- Actual Owl 3 component/templates rendered and compiled alongside Slack and
  WhatsApp. Native save/RPC/reload, failed-save guard, secret clearing and
  desktop/mobile layout passed.
- Clean Odoo install with all four providers and repeated Teams upgrade passed.
  Native Form/web_save, result forgery, operator/outsider/portal access, signed
  activity, inbox dedup, immutable route, blocked tester, durable diagnostic claim,
  repeat prevention, setup completion and receipt withdrawal were exercised.
- Explicit reply enable/pause controls require current completed setup, scoped
  manager, verified sender and active company approval policy. The global cron
  stays separately controlled.

No live Microsoft requests, emails or provider messages were sent. Real Azure
Bot registration, tenant credentials, callback delivery and receipt still require
an integration check with a real tenant.
