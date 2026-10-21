# Verification

Offline checks, 2026-10-11:
- 44 transport/provider/webhook tests: fixed hosts, bounded responses, TLS/no redirects or
  ambient proxies, token injection, scoped encrypted vault, profile/Page ownership,
  restricted LinkedIn reads, exact actor/destination, Instagram 24-hour private
  window, photo processing stages, no second upload, ambiguous-result handling.
- Actual Odoo 20 disposable install/upgrade with Instagram, LinkedIn, Telegram,
  WhatsApp, Slack and Teams together; native account/publication Forms, view checks,
  company/team/portal/operator isolation, forged defaults/results/approver evidence,
  distinct approver, frozen content, stale account, revoked private agreement,
  committed claim visible before simulated POST, no duplicate/unknown retry,
  immutable photo hash, staged photo continuation and activity retention.
- Ordered-media extension: exact child order/hash, frozen child CRUD/defaults,
  scoped file access, per-index public serving only during claims, automatic staged
  continuation with committed IDs, real MP4 probing and disguised-JPEG rejection, signed endpoint rejects tampering, duplicates
  produce one receipt, inbound cron imports without calling execute, disable works.
- Owl 3 widget test (now the Hoot suite `static/tests/credentials.test.js`, run by `tests/test_ui.py`): rendering, conditional Page ID, save/RPC/reload,
  transient token/app-secret clearing, failed-save guard, desktop/mobile bounds.
- Existing connector regressions: 18 Slack, 19 Teams, 44 WhatsApp, 6 Omnichannel
  view and 4 Telegram view tests.

Commands (all checks run under Odoo's test runner since 2026-10-21):
```
./odoo-bin -d <test-db> -i omni_instagram,omni_linkedin,social_ai,social_home \
  --test-tags /omni_social,/social_ai,/social_home --stop-after-init
.venv/bin/python addons/omni_social/tools/check_install.py
```

Live platform checks are listed in `LIVE_CHECKS.md`; record results there.

The install tool blocks `requests.Session.request/get/post`, SMTP and account
invitations and deletes its disposable database. Provider fixtures are synthetic;
they do not prove Meta/LinkedIn app approval, real payload compatibility, public
media URL reachability, live publication or delivery. No live content was sent. Final regression total: 135 pure tests (44 social,
18 Slack, 19 Teams, 44 WhatsApp, 6 Omnichannel views, 4 Telegram views), plus
the real Odoo database and Owl browser checks.
