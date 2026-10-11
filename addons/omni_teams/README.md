# Microsoft Teams for Omnichannel

Connect a single-tenant Microsoft Teams bot, receive its personal text chats in
Odoo and send replies through the existing recipient-consent and Approval Center
pipeline. This is a Bot Connector integration, not a Graph account that reads all
staff chats. Group chats, channels, files, adaptive cards, multi-tenant apps,
Emulator authentication, sovereign clouds and OAuth onboarding are outside scope.

## Setup

1. Create a single-tenant Azure Bot and Microsoft Entra application at
   https://portal.azure.com/#create/Microsoft.AzureBot. Enable its Teams channel.
   Package/install a Teams app with this bot in `personal` scope.
2. In Credentials, enter the Microsoft app ID, tenant ID and client secret.
3. Save the public HTTPS URL in Connect & verify. Paste it into the Azure Bot's
   Messaging endpoint. Enable receiving with the displayed retention periods.
4. Set internal branding.
5. Ask the tester to message the bot, choose that received chat, send the fixed
   test, confirm receipt and finish setup. The chat shows the tester's name.

Credentials are encrypted in private files beneath Odoo's data directory, scoped
by database/company/team/tenant/app. Securely back up that directory. Use a
host-bound database (`dbfilter`) and a public HTTPS reverse proxy.

## Authentication and routing

Connector authentication follows Microsoft's published REST requirements: RSA
signature, fixed trusted OpenID/JWK discovery, RS256 only, issuer, app audience,
expiry/not-before, Teams key endorsement, signed service URL and configured
activity tenant/bot recipient. There is no verification bypass. Metadata is
cached for up to 24 hours, unknown keys trigger bounded refresh, and refreshes
are throttled to prevent untrusted requests causing unbounded discovery traffic.

Only personal human text is normalized. Teams' alternate `text/html` attachment
is ignored; plain text is used and HTML is never rendered or fetched. Real file
attachments are ignored. One bounded native normalization records the verified
service URL/member route alongside the text in the same transaction. These
routing fields cannot be supplied or edited by users, including managers.
Duplicate activities use the native durable event tombstones.

Replies carry a sealed, server-derived conversation route in the approval
payload. Only the commercial-cloud Teams service host and documented geography
paths are allowed; no redirects or user-defined destination hosts. The Connector
activity POST occurs once, after the framework's committed authorization claim.
Uncertain acceptance is never automatically retried.

## Approved replies

Choose an active Message approval type in channel settings and explicitly click
**Enable approved replies**. Recipient consent and each message's Approval Center
review still apply. **Pause replies** stops new claims. A system administrator
separately enables the existing `omni_channel.cron_dispatch` scheduled action.
Setup never enables that global scheduler or sends arbitrary messages.

A manager's setup test confirmation permits one fixed
`Teams connection test successful.` message to the selected recent verified
personal chat. Pending/accepted/uncertain tests cannot repeat. Only a definitive
not-sent result allows another explicit attempt. Receipt withdrawal deactivates
the sender and clears the final milestone.

## Checks

- `python -m unittest discover -s addons/omni_teams/tests`
- `python addons/omni_teams/tools/check_install.py` — disposable database;
  installs Slack/Telegram/WhatsApp/Teams together, upgrades Teams, tests native
  forms, role/company/team boundaries, immutable routing, inbox deduplication,
  diagnostic claims, completion and explicit reply activation/pause. External
  requests and email are blocked. Test records and database are removed.
- `OMNI_NODE_MODULES=<bundled node_modules> node addons/omni_teams/tools/test_ui.cjs`
  — actual Owl 3 component/templates and desktop/mobile layout.

Live Microsoft authentication and delivery require a real registered bot/tenant.
Mocked checks are not evidence of live deployment certification.
