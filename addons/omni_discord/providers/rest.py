"""Fixed-host Discord REST calls with a bot token: no redirects, proxies or automatic retries."""

import json
import re
import time

import requests

HOST = "discord.com"
BASE = "/api/v10"
MAX_RESPONSE = 256 * 1024
USER_AGENT = "DiscordBot (https://github.com/odoo/odoo, 20.0) omni_discord"


class RestError(Exception):
    def __init__(self, code, sent=False, retry_after=0):
        super().__init__(code)
        self.code, self.sent, self.retry_after = code, sent, retry_after


def snowflake(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{14,21}", value) is not None


def call(token, path, *, method="GET", body=None, session_factory=requests.Session):
    if (
        not isinstance(token, str) or not token or len(token) > 200 or any(c in token for c in "\r\n ")
        or not path.startswith("/") or "?" in path or "#" in path or ".." in path or method not in ("GET", "POST")
    ):
        raise RestError("request")
    session = session_factory()
    session.trust_env = False
    response = None
    try:
        started = time.monotonic()
        response = session.request(
            method, "https://%s%s%s" % (HOST, BASE, path), json=body, timeout=(5, 15),
            headers={"Authorization": "Bot " + token, "User-Agent": USER_AGENT},
            allow_redirects=False, stream=True, verify=True,
        )
        raw = bytearray()
        for chunk in response.iter_content(8192):
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE or time.monotonic() - started > 20:
                raise RestError("response", sent=method == "POST")
        status = response.status_code
        value = json.loads(raw) if raw else {}
        if status == 429:
            delay = value.get("retry_after") if isinstance(value, dict) else None
            raise RestError("rate_limited", retry_after=delay if isinstance(delay, (int, float)) else 5)
        if status in (401, 403):
            raise RestError("unauthorized")
        if status in (400, 404):
            raise RestError("rejected")
        if not 200 <= status < 300:
            raise RestError("server", sent=method == "POST")
        if not isinstance(value, dict):
            raise RestError("response", sent=method == "POST")
        return value
    except RestError:
        raise
    except (requests.RequestException, ValueError):
        raise RestError("network", sent=method == "POST") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def bot(token):
    me = call(token, "/users/@me")
    if not snowflake(me.get("id")) or me.get("bot") is not True:
        raise RestError("not_bot")
    return me["id"], (me.get("global_name") or me.get("username") or me["id"])[:256]
