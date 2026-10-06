"""Deployment-provisioned secrets bound to one database/company/bot."""

import json
import os
import re
from dataclasses import dataclass


class TelegramConfigurationError(Exception):
    def __init__(self):
        super().__init__("Telegram configuration is unavailable or invalid.")


def canonical_id(value):
    if type(value) is int and 0 < value < 2**52:
        return str(value)
    if (
        isinstance(value, str)
        and re.fullmatch(r"[1-9][0-9]{0,15}", value)
        and int(value) < 2**52
    ):
        return value
    raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation


@dataclass(frozen=True, repr=False)
class TelegramSecrets:
    token: str
    webhook_secret: str


def resolve(reference, config, environ=None):
    environ = os.environ if environ is None else environ
    try:
        if not isinstance(reference, str) or not re.fullmatch(
            r"OMNI_SECRET_[A-Z0-9_]{1,100}", reference,
        ):
            raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation
        raw = environ.get(reference, "")
        if not isinstance(raw, str) or len(raw) > 8192:
            raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation
        value = json.loads(raw)
        binding = config["adapter"]
        bot = canonical_id(config["account_key"])
        if (
            not isinstance(value, dict)
            or value.get("database") != binding["database"]
            or type(value.get("company_id")) is not int
            or value["company_id"] != binding["company_id"]
            or value.get("bot_id") != bot
            or config["namespace"] != bot
        ):
            raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation
        token, secret = value["token"], value["webhook_secret"]
        if (
            not isinstance(token, str)
            or not re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{20,128}", token)
            or token.split(":", 1)[0] != bot
            or not isinstance(secret, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret)
        ):
            raise TelegramConfigurationError()  # noqa: TRY301 - sanitized boundary validation
        return TelegramSecrets(token, secret)
    except Exception:  # noqa: BLE001 - never include JSON/env material or chained exceptions
        raise TelegramConfigurationError() from None
