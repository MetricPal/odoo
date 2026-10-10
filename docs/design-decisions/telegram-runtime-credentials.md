# Telegram runtime credentials

Users configure Telegram connections with company selection and masked token
entry. The active database comes from `env.cr.dbname`. The adapter performs
read-only `getMe` verification before accepting runtime credentials; bot ID and
public metadata are derived from this response. Runtime identity verification
is separate from sandbox authorization, receiving activation and approved sends.

The existing provider contract carries only an opaque credential reference. To
preserve this boundary, new credentials use encrypted private files beneath
Odoo's configured data directory rather than token-bearing ORM fields or dispatch
claims. Non-stored input fields are consumed by create/write and read back empty.
A scoped resolver validates database, company and bot on every credential use.
Legacy environment references continue to resolve unchanged.

This is a deployment-local credential store, not a managed external vault. Its
key and encrypted files require restricted shared storage and backups like other
Odoo runtime data. Host administrators remain trusted. Immutable references
preserve in-flight claim semantics; previous versions are retained until an
administrator confirms they are no longer referenced. See the adapter README
for rotation, rollback and orphan cleanup behavior.

Only Omni administrators within the current company/team scope may submit or
retrieve webhook credentials. A manager-only transient disclosure view computes
the webhook secret on demand and never stores it in the transient table. Tokens
cannot be disclosed through record reads. No user credential is sent anywhere
except the fixed Telegram HTTPS endpoint during requested verification/use.

The manager's Connect Telegram action is the explicit authorization boundary for
webhook registration. It resolves the scoped credentials server-side, passes the
secret directly to Telegram and preserves pending updates. Replacing a different
remote URL requires a confirmation with local and remote state fingerprints.
The registration transport capability is restricted to setWebhook and does not
enable sending. Unknown external outcomes are audited and surfaced for read-only
verification, with no automatic mutation retry. Test-user IDs are entered in the final step. Its explicit test confirmation
activates test-user receiving under the displayed retention policy before the
fixed diagnostic is claimed. Connection readiness tracks the registered callback
and verified credential identity independently of intake readiness. Replies
remain separately authorized. The manual secret disclosure view remains available on the account for
administrators, but is removed from guided channel setup.

Completed Telegram channel forms now use the approved compact overview. Native
Odoo modal forms expose channel settings and test-user edits without sender/endpoint
technical tables. Manager-only saves preserve scope, immutable retention history,
public activation actions and audit records. Test-user changes pause replies and
advance send generations; a failed reauthorization rolls back the change. Operators
can open the scoped inbox, but cannot read or edit test-user lists. Odoo 20's view
inheritance matches the first XPath result, so each legacy sheet child is hidden
explicitly for Telegram; other provider forms retain their existing surfaces.

The compact completed-channel summary is also available in kanban and list views:
Connected status, test users and Settings/Inbox/Edit test users actions. Incomplete
records retain their guided setup actions. Progress is a readonly registered Odoo
20 field widget with five segments and a trailing count; no global click or CSS
interaction overrides were added. Company/team permissions and manager-only test
user visibility apply to the quick actions as well as the dialogs.

Odoo 20's bundled Owl 3 rejects static component props schemas and resolves
component members through `this` in templates. The progress widget follows the
native ProgressBarField's `useProps` pattern. A real-browser mount/update regression
check supplements XML/schema and compiler tests, which cannot catch lifecycle errors.

The card layout was simplified further: a single continuous progress bar replaces
segments. Channel type sits at top-right with readiness directly beneath. Sender
labels, sender/endpoint counts and dividers are removed. Completed-card footer is
Edit test users / Inbox on the left and Settings on the right; incomplete cards keep
Start/Continue setup at bottom-right. Bot and receiving status use separate lines.
