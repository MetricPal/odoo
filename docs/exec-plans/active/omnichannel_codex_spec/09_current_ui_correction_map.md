# 09 — Current UI Correction Map

This is the direct mapping from the current implementation to the required final architecture.

## Current "Set up once. Let your team work from Inbox."

STATUS: KEEP AS A WIZARD, MOVE OUT OF PERMANENT HOME.

It is the Add Channel wizard.

It must not be the normal Overview dashboard.

## Current "Prepared Messages / New message"

STATUS: KEEP THE UNDERLYING MESSAGE/DISPATCH MODEL, REDESIGN PRIMARY VIEW.

Hide/move:
- Provider Message Key
- Attempt Count
- Next Attempt At
- Lease Expires At
- raw dispatch internals

Keep primary message/business fields visible.

## Current "Outbound Senders / New"

STATUS: KEEP CONCEPT, REDESIGN UX.

Make active sender selection explicit.

Enforce:
multiple configured
+
exactly one active runtime sender
+
health check before activation.

## Current "Inbound Endpoints / New"

STATUS: KEEP CONCEPT, REDESIGN UX.

Add/clearly expose:
Business Purpose / Team / Module ownership.

Hide technical routing/version identifiers under Technical Details.

## Current "Channels"

STATUS: KEEP AS CENTRAL RECORD.

Reorganize:
identity/status first
sender summary
inbound summary
operations
alerts
technical details

## Current "Connections / New"

STATUS: KEEP CONCEPT, CLEAN UP PRESENTATION.

Treat it as provider-account connection infrastructure.

Do not expose secrets.

## Current "Recipient Authorization"

STATUS: TECHNICAL/ADVANCED DATA.

Do not make it a primary Omni-Channel navigation destination for ordinary operators.

Expose it only where authorization details are operationally required or through technical views.

## Current "Receiving & retention rules"

STATUS: MOVE UNDER Configuration → Policies.

Do not place it in the primary Add Channel wizard unless a specific policy is required to complete setup.

## Current "Advanced configuration"

STATUS: DELETE THE LABEL.

Replace with:
Configuration

## Current top navigation

Required:
Overview | Inbox | Messages | Channels | Monitoring | Configuration

No extra top-level "Advanced Configuration".
