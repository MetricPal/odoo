# 07 — Blocklist

## PURPOSE

Prevent unwanted inbound identities from entering normal business processing.

## RECORD

Primary fields:
- External identity
- Channel
- Scope
- Business purpose (when scoped)
- Reason
- Status
- Created by
- Created at

Optional:
- Expiry
- Notes

Technical evidence may exist but should be secondary.

## SCOPES

Support:
- Channel + Business Purpose
- Global scope where explicitly enabled

## PROCESSING

Blocklist check occurs before normal business processing.

AI classification/recommendation may assist, but changing organizational/system state follows the project's human approval rule unless an explicit approved automation policy exists.
