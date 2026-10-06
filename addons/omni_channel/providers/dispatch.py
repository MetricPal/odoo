"""Transport boundary: immutable input, no ORM records, no implicit retries."""

import json
import math
import re
from dataclasses import dataclass

from .base import AdapterUnavailable, get_adapter


@dataclass(frozen=True)
class DispatchClaim:
    command_id: int
    attempt_id: int
    token: str
    command_uuid: str
    provider: str
    payload_json: str
    account_key: str
    namespace: str
    sender_key: str
    credential_reference: str


@dataclass(frozen=True)
class DispatchResult:
    outcome: str
    provider_message_key: str = ""
    retryable: bool = False
    retry_after: float = 0
    reason_code: str = ""


def normalize_result(result):
    """Malformed responses after dispatch are uncertain, never safe to retry."""
    if (
        not isinstance(result, DispatchResult)
        or not isinstance(result.outcome, str)
        or result.outcome not in {"accepted", "definitely_not_sent", "unknown"}
    ):
        return DispatchResult("unknown", reason_code="invalid_result")
    if (
        type(result.retryable) is not bool
        or type(result.retry_after) not in (int, float)
        or not math.isfinite(result.retry_after)
        or not 0 <= result.retry_after <= 86400
    ):
        return DispatchResult("unknown", reason_code="invalid_result")
    if result.outcome == "accepted" and (
        not isinstance(result.provider_message_key, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:@+/=-]{1,256}", result.provider_message_key)
    ):
        return DispatchResult("unknown", reason_code="invalid_result")
    code = (
        result.reason_code
        if isinstance(result.reason_code, str)
        and result.reason_code
        in {
            "rate_limited",
            "unauthorized",
            "invalid_recipient",
            "transport",
            "unsupported",
            "unhealthy",
            "invalid_result",
        }
        else ""
    )
    return DispatchResult(
        result.outcome,
        result.provider_message_key if result.outcome == "accepted" else "",
        result.retryable if result.outcome == "definitely_not_sent" else False,
        result.retry_after,
        code,
    )


def dispatch_claim(claim):
    """Exactly one send invocation. Preflight methods must be read-only and bounded.

    Adapters must impose HTTP connect/read timeouts of at most 5/20 seconds.
    No adapter transport ships in this increment; mocks exercise this boundary.
    """
    try:
        adapter = get_adapter(claim.provider)
        if not getattr(adapter, "dispatch_supported", False):
            return DispatchResult("definitely_not_sent", reason_code="unsupported")
        payload = json.loads(claim.payload_json)
        config = {
            "account_key": claim.account_key,
            "namespace": claim.namespace,
            "sender_key": claim.sender_key,
            "credential_reference": claim.credential_reference,
        }
        health = adapter.check_sender_health(config)
        if not (
            health.healthy
            and health.namespace == claim.namespace
            and health.account_key == claim.account_key
            and health.sender_key == claim.sender_key
        ):
            return DispatchResult("definitely_not_sent", reason_code="unhealthy")
        if adapter.validate_command(payload, config) is not True:
            return DispatchResult(
                "definitely_not_sent", reason_code="invalid_recipient",
            )
    except AdapterUnavailable:
        return DispatchResult("definitely_not_sent", reason_code="unsupported")
    except Exception:  # noqa: BLE001 - preflight is read-only; never store provider exceptions
        return DispatchResult(
            "definitely_not_sent", retryable=True, reason_code="transport",
        )
    try:
        # Pass the immutable original, not the potentially mutated validation copy.
        return normalize_result(adapter.dispatch(claim))
    except Exception:  # noqa: BLE001 - once invocation begins, acceptance may be unknown
        return DispatchResult("unknown", reason_code="transport")
