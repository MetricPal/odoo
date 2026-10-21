# Security and Authorization

## Security model

Authorization is enforced independently of AI.

AI is never an authorization source.

## Required dimensions

Evaluate as applicable:
- Odoo user type
- groups
- access rights
- record rules
- company
- model/record
- relationship
- application/module
- workflow state
- automation policy

## External users

Portal and public users must receive only the data/actions explicitly available to them.

A public or portal AI agent must not expose internal ERP data simply because it can answer a question about the organization.

## Secrets

Never commit credentials, tokens, private keys or production secrets.

## Audit

Security-sensitive AI decisions, tool calls, approvals and executions must be auditable.

## Credential storage

Provider credentials (Slack, Teams, WhatsApp, Instagram/LinkedIn) are encrypted
files under the Odoo data directory. By default the encryption key is stored next
to them, which does not protect against someone who can read that directory. Set
`OMNI_VAULT_KEY` (a Fernet key) in the Odoo process environment to keep the key
elsewhere; bundles written before stay readable, and comma-separated keys allow
rotation (new key first). Back up the key with the data directory.

## Passwordless sign-in

Magic links are single-use, expire within 60 minutes, are requested with exact
email matching, throttled per address and per account, sent through the mail
queue, and consumed only by an explicit POST after a confirmation page. No public
endpoint reveals whether an account exists or what its email address is.

## Omni system administration

System Administrators (`base.group_system`) inherit Omni Administrator access
by default and can administer all communication purposes without individual
Authorized team enrollment. This applies to Omni record scope, including related
communication audit and linked approval scope. Existing Approval Center rules
still apply. Ordinary Omni administrators and operators still require purpose
membership. All roles retain Odoo's selected-company restriction and company
consistency checks; select the relevant authorized company before configuring it.

This is administrative access, not superuser execution: protected runtime fields,
append-only audit history, designated approver checks, and explicit approval for
sending or enabling automation remain enforced.
