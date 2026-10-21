"""Fixed-host Graph API calls for one Page: no redirects, proxies or automatic retries."""

import json
import re
import time

import requests

HOST = "graph.facebook.com"
VERSION = "v25.0"
MAX_RESPONSE = 512 * 1024


class GraphError(Exception):
    """Fixed codes only; ``sent`` says whether a POST may have reached Meta."""

    def __init__(self, code, sent=False, status=0):
        super().__init__(code)
        self.code, self.sent, self.status = code, sent, status


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,31}", value) is not None


def call(token, path, *, method="GET", params=None, body=None, session_factory=requests.Session):
    if (
        not isinstance(token, str) or not token or len(token) > 4096 or any(c in token for c in "\r\n")
        or not path.startswith("/") or "?" in path or "#" in path or ".." in path
        or method not in ("GET", "POST")
    ):
        raise GraphError("request")
    session = session_factory()
    session.trust_env = False
    response = None
    try:
        started = time.monotonic()
        response = session.request(
            method, "https://%s/%s%s" % (HOST, VERSION, path), params=params, json=body,
            headers={"Authorization": "Bearer " + token}, timeout=(5, 10),
            allow_redirects=False, stream=True, verify=True,
        )
        raw = bytearray()
        for chunk in response.iter_content(8192):
            raw.extend(chunk)
            if len(raw) > MAX_RESPONSE or time.monotonic() - started > 20:
                raise GraphError("response", sent=method == "POST")
        status = response.status_code
        if status == 429:
            raise GraphError("rate_limited", status=status)
        if status in (401, 403):
            raise GraphError("unauthorized", status=status)
        if status == 400:
            raise GraphError("rejected", status=status)
        if not 200 <= status < 300:
            # A server error after a POST does not prove the message was not sent.
            raise GraphError("server", sent=method == "POST", status=status)
        value = json.loads(raw) if raw else {}
        if not isinstance(value, dict):
            raise GraphError("response", sent=method == "POST")
        return value
    except GraphError:
        raise
    except (requests.RequestException, ValueError):
        raise GraphError("network", sent=method == "POST") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def page(token):
    """The Page this token belongs to; user tokens (no category) are refused."""
    value = call(token, "/me", params={"fields": "id,name,category"})
    if not identifier(value.get("id")) or not isinstance(value.get("name"), str) or not value.get("category"):
        raise GraphError("page_token")
    return value["id"], value["name"][:256]
