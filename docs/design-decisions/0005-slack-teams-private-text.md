# Slack and Microsoft Teams private-text connectors

2026-10-11. The user approved building Slack first, committing it, then building
and committing Microsoft Teams. Implement separate optional addons; keep
`omni_channel`, `omni_telegram` and `omni_whatsapp` source unchanged.

Slack connects an existing bot token/signing secret/app ID and verifies signed
Events API callbacks. Teams connects an existing single-tenant Bot Connector
app/tenant/secret and validates Microsoft's endorsed RSA JWTs. Neither requests
broad Graph access to employee chats. Both normalize private human text into the
existing company/team scoped inbox and use the existing command approval/outbox
for replies. Unsupported channel/group/file activities are ignored.

```mermaid
flowchart LR
  Provider[Slack or Teams] --> Verify[Provider authentication and scope]
  Verify --> Inbox[Existing durable private inbox]
  Inbox --> Draft[Reply draft]
  Draft --> Consent[Recipient consent]
  Consent --> Approval[Approval Center]
  Approval --> Claim[Committed dispatch claim]
  Claim --> Send[One provider POST]
```

Five setup steps stay at the existing level: Prepare → Credentials → Connect &
verify → Branding → Test & go live. Secrets live only in transient browser fields
and encrypted scoped private files. Tester data belongs on the final step. Teams
uses a received-chat selector with a protected sender name rather than requiring
the user to locate an Entra object ID.

Slack acknowledges durable storage before native background normalization.
Teams additionally performs one bounded native normalization in its ingress
transaction to attach its authenticated service URL and member route to the same
conversation atomically. A separate worker/model/database architecture is not
introduced. Teams routing is protected from all direct user writes and sealed
in message approval payloads.

Setup tests have independent committed claims. Unknown outcomes never resend.
Normal replies require explicit channel activation and per-message governance;
the existing global dispatch scheduler remains separately controlled.

Offline install/upgrade, security, browser and mocked-provider checks cover the
implemented scope. Real credentials and delivery must still be checked with live
Slack and Teams accounts. OAuth onboarding, files, shared/group channels and
sovereign clouds remain outside this release.
