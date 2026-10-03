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
