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
