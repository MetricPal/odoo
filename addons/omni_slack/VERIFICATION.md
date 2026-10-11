# Verification — 2026-10-11

- 18 pure protocol/API/vault tests passed: signature mutation, clock window,
  duplicate keys, challenge authentication, workspace/app binding, human private
  text filtering, API outcomes, uncertain-send no retry and encrypted scope.
- Actual Owl 3 component and inherited template compiled/rendered; desktop/mobile
  layout, native save/RPC/reload, failed-save guard and secret clearing passed.
- Isolated Odoo clean installation and repeated upgrade passed; native Form and
  web_save, operator/outsider/portal denial, forged diagnostic results, callback
  verification, duplicate delivery, inbox normalization, blocked tester, durable
  claim, no repeated send, completion and receipt withdrawal passed.
- Reply execution has a separate private-conversation/recipient-binding check.
- No provider requests, invitations or live Slack messages were sent in tests.

Live workspace credentials, HTTPS callback routing and real Slack delivery cannot
be certified by mocks. A real app is required for that final deployment check.

Reply activation/pause controls additionally check manager/team/company access,
current sender and generation, complete tested setup and active approval policy.
They never approve an individual message or activate the global scheduler.
