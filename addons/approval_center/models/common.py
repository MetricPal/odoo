"""Server-side capabilities for governed writes.

An object identity in the environment context cannot be forged through
JSON-RPC (which can only send JSON values), unlike a boolean context flag.
Each module keeps its own capability so one module's internal writes never
unlock another module's protected fields.
"""


def capability(context_key):
    """Return ``(grant, check)`` helpers for a new private capability.

    ``grant(records)`` returns the records allowed to perform the module's
    internal writes; ``check(records)`` tells whether they carry it.
    """
    token = object()

    def grant(records):
        return records.with_context(**{context_key: token})

    def check(records):
        return records.env.context.get(context_key) is token

    return grant, check


approval_internal, approval_token_present = capability('_approval_center_token')
