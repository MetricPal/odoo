# Testing and Verification Skill

For every substantial change:
- inspect relevant existing tests
- add/update tests
- run targeted tests first
- run broader tests when practical
- verify permissions/security
- verify UI behavior when applicable
- report exact commands/results

Do not report a test as passed if it was not actually run.

## XML/view validation notes

- If `xmllint` is unavailable, use a lightweight parser fallback such as
  `python3 -m xml.etree.ElementTree path/to/file.xml` for XML well-formedness.
- When Python tooling reports an interpreter path, verify that executable exists
  before using it. If the configured venv path is stale, use an available system
  Python only for dependency-free checks such as XML parsing, and report that
  fallback clearly.
- Pair parser checks with editor diagnostics for Odoo XML views; parser success
  only proves well-formed XML, not semantic validity of Odoo fields or widgets.
