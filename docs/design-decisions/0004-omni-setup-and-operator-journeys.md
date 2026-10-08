# Omni setup and operator journeys

The initial interface exposed the transport data model as the onboarding journey.
Channel cards did not explain the next step, and operators saw setup surfaces.
The product now distinguishes the setup administrator from the daily operator.

## Technical administration — revised 2026-10-08

The user superseded the standalone-workspace specification with a simpler Email-
style technical component. Omni-Channel is not an application/launcher entry.
Settings → Technical → Omni-Channel precedes Email and is visible only to
system administrators in developer mode.

Only Channels, Messages, Policies and Blocklist remain as navigation destinations.
Channels use standard list/form views. Connections and messages open from the
channel, senders/endpoints remain in its tabs, and diagnostics/recipient
authorization open from Operations → Technical Details. The setup transient,
welcome page, Overview and redundant menus are removed on upgrade.

Business applications retain access to the existing scoped inbox actions and
runtime APIs. This change does not build new business-app integrations or change
the message approval, dispatch, blocklist or company/purpose authorization rules.
System administrators inherit the Omni role; delegated runtime roles remain
available for existing business integrations without exposing Technical menus.

## Identity and permission

The legacy External Account Key is labeled Provider account ID. In Telegram it
is the public numeric bot ID, not a token or username. Telegram connection setup
derives bot ID and namespace from the selected deployment-provisioned secret
reference, validated for this database and selected company. Only administrators
may discover it. No token is returned to the form. Sender and endpoint identities
default from that connection. Existing explicit identities remain supported at
the ORM boundary for compatibility; provider health checks still verify them.

A deployment administrator must provision the scoped secret, network switch,
public webhook and workers. This is not yet an OAuth-style self-service connector.
The supported Telegram contract remains private-text sandbox processing for up
to ten explicitly authorized test users. Other catalog entries are not promises
of installed provider support.

Recipient permission opens from an Inbox conversation with its exact channel,
namespace and destination prefilled. Evidence, expiry review and explicit
confirmation remain human decisions. Existing records are shown first to avoid
blindly creating duplicates. This implementation still requires current
recipient permission for every outbound message, independently of message
approval; receiving a message does not automatically grant permission.

## Receiving rules

The former Inbound Policies surface is labeled Receiving & retention rules.
One active policy covers one channel and may serve multiple endpoints. It
authorizes ingestion and retention disposal, not replies, contact creation,
business changes or AI disclosure. Defaults (7/90/30 days) are visible examples,
not universal retention advice. Activation, pausing and holds remain explicit.

## Verification and release

Test routing and menu visibility for administrator/operator/portal users, scope
propagation, recipient context without implicit consent, and Telegram identity
derivation including wrong-company rejection and secret non-disclosure. Validate
updated views with both core and Telegram installed. Upgrade both modules and
restart to apply. No live provider or organizational configuration is changed by
development tests.

## Form clarity and monitoring — 20.0.1.9.0

Technical Messages uses a separate primary read-only view and action. It does
not expose New, Submit for approval, Queue or Cancel controls. Existing business
actions keep their composition/approval flow; monitoring retains review and
unknown-outcome reconciliation. Channel message shortcuts use the monitor.

Policy, blocklist and message forms use labels above full-width inputs within
a responsive two-column grid. Explanations appear beside each setting instead
of in a large technical banner. Blocklist connection selection fills and checks
company/provider/account scope. Provider availability is shown explicitly;
saving a catalog configuration is never represented as a working connection.
