"""Derive channel ingress from backend configuration without network access."""

import ipaddress
import re
from urllib.parse import urlsplit


def channel_origin(base_url):
    """Use the configured hostname, preserving subdomains and tenant boundaries."""
    try:
        parsed = urlsplit(base_url or "")
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return False
        if any(char.isspace() for char in base_url):
            return False
        if not host or len(host) > 253 or "." not in host:
            return False
        if host.rsplit(".", 1)[-1] in ("localhost", "local", "internal"):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return False
        if host.rsplit(".", 1)[-1].isdigit() or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            return False
        host = host if host.startswith("channels.") else f"channels.{host}"
        return f"https://{host}" if len(host) <= 253 else False
    except (ValueError, UnicodeError):
        return False
