# Verification

Offline checks, 2026-10-11:
- 30 transport/provider tests: fixed hosts, bounded responses, TLS/no redirects or
  ambient proxies, token injection, scoped encrypted vault, profile/Page ownership,
  restricted LinkedIn reads, exact actor/destination, Instagram 24-hour private
  window, photo processing stages, no second upload, ambiguous-result handling.
- Actual Odoo 20 disposable install/upgrade with Instagram, LinkedIn, Telegram,
  WhatsApp, Slack and Teams together; native account/publication Forms, view checks,
  company/team/portal/operator isolation, forged defaults/results/approver evidence,
  distinct approver, frozen content, stale account, revoked private agreement,
  committed claim visible before simulated POST, no duplicate/unknown retry,
  immutable photo hash, staged photo continuation and activity retention.
- Actual Owl 3 widget test: rendering, conditional Page ID, save/RPC/reload,
  transient token clearing, failed-save guard, desktop/mobile bounds.
- Existing connector regressions: 18 Slack, 19 Teams, 44 WhatsApp, 6 Omnichannel
  view and 4 Telegram view tests.

Commands:
```
.venv/bin/python -m unittest discover -s addons/omni_social/tests -p test_protocol.py
.venv/bin/python addons/omni_social/tools/check_install.py
OMNI_NODE_MODULES=/path/to/node_modules node addons/omni_social/tools/test_ui.cjs
```

The install tool blocks `requests.Session.request/get/post`, SMTP and account
invitations and deletes its disposable database. Provider fixtures are synthetic;
they do not prove Meta/LinkedIn app approval, real payload compatibility, public
media URL reachability, live publication or delivery. No live content was sent.
