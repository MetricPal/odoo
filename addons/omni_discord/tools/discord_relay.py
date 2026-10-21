#!/usr/bin/env python3
"""Discord gateway relay for Omnichannel (omni_discord).

Discord delivers new messages only over a permanently open gateway
connection, which Odoo's request workers cannot hold. This small program
holds it and forwards each new text message to the channel's inbound URL,
signed with the relay secret shown in the channel setup. It never sends
anything to Discord itself: replies are sent by Odoo after approval.

Run it next to Odoo (systemd, Docker, tmux...):

    DISCORD_BOT_TOKEN=... OMNI_RELAY_SECRET=... \\
        python3 discord_relay.py --url https://odoo.example.com/omni/inbound/<route> --bot <bot id>

Needs: requests, websocket-client (both ship with Odoo's requirements).
In the Discord Developer Portal, turn on the bot's "Message Content Intent".
"""

import argparse
import hashlib
import hmac
import json
import logging
import os
import random
import sys
import threading
import time

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
# GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT (privileged; enable it for the bot)
INTENTS = (1 << 9) | (1 << 12) | (1 << 15)

_logger = logging.getLogger("discord_relay")


def sign(secret, raw, timestamp=None):
    timestamp = str(int(timestamp if timestamp is not None else time.time()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"X-Omni-Relay-Signature": "sha256=" + digest, "X-Omni-Relay-Timestamp": timestamp,
            "Content-Type": "application/json"}


def to_relay(event, bot_id):
    """Keep only what Odoo needs from a MESSAGE_CREATE event; None for bots and empty text."""
    author = event.get("author") or {}
    if author.get("bot") or author.get("id") == bot_id or not (event.get("content") or "").strip():
        return None
    return {
        "id": event.get("id"), "channel_id": event.get("channel_id"), "guild_id": event.get("guild_id") or "",
        "author": {"id": author.get("id"), "username": author.get("username"),
                   "global_name": author.get("global_name"), "bot": bool(author.get("bot"))},
        "content": event.get("content"), "timestamp": event.get("timestamp"),
    }


class Forwarder:
    """Signed POSTs to Odoo with bounded retries; a rejected batch is dropped and logged."""

    def __init__(self, url, secret, bot_id, session=None, sleep=time.sleep):
        import requests

        self.url, self.secret, self.bot_id = url, secret, bot_id
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.sleep = sleep

    def send(self, messages):
        raw = json.dumps({"bot_id": self.bot_id, "messages": messages}, separators=(",", ":")).encode()
        for attempt in range(5):
            try:
                response = self.session.post(self.url, data=raw, headers=sign(self.secret, raw), timeout=(5, 20),
                                             allow_redirects=False)
                if response.status_code == 200:
                    return True
                if response.status_code in (400, 403, 404):
                    _logger.error("Odoo rejected %s message(s) (HTTP %s); check the URL and relay secret.",
                                  len(messages), response.status_code)
                    return False
            except Exception as error:  # noqa: BLE001 - keep relaying; Odoo deduplicates by message id
                _logger.warning("Could not reach Odoo (%s); retrying.", type(error).__name__)
            self.sleep(min(2 ** attempt, 30))
        _logger.error("Giving up on %s message(s) after 5 attempts.", len(messages))
        return False


class Gateway:
    def __init__(self, token, forwarder, bot_id, connect=None, sleep=time.sleep):
        self.token, self.forwarder, self.bot_id = token, forwarder, bot_id
        self.connect = connect
        self.sleep = sleep
        self.sequence = None
        self.stop = threading.Event()

    def _open(self):
        if self.connect:
            return self.connect()
        import websocket

        return websocket.create_connection(GATEWAY, timeout=90)

    def _heartbeat(self, ws, interval):
        self.sleep(interval * random.random())
        while not self.stop.is_set():
            try:
                ws.send(json.dumps({"op": 1, "d": self.sequence}))
            except Exception:  # noqa: BLE001 - the reader notices the closed socket
                return
            if self.stop.wait(interval):
                return

    def session(self):
        """One gateway session; returns when Discord asks to reconnect or the socket closes."""
        ws = self._open()
        try:
            hello = json.loads(ws.recv())
            if hello.get("op") != 10:
                raise RuntimeError("expected HELLO")
            interval = hello["d"]["heartbeat_interval"] / 1000
            beat = threading.Thread(target=self._heartbeat, args=(ws, interval), daemon=True)
            beat.start()
            ws.send(json.dumps({"op": 2, "d": {"token": self.token, "intents": INTENTS, "properties": {
                "os": sys.platform, "browser": "omni_discord", "device": "omni_discord"}}}))
            while not self.stop.is_set():
                frame = ws.recv()
                if not frame:
                    return
                message = json.loads(frame)
                if message.get("s") is not None:
                    self.sequence = message["s"]
                op = message.get("op")
                if op == 0 and message.get("t") == "READY":
                    _logger.info("Connected to Discord as %s.", (message["d"].get("user") or {}).get("username"))
                elif op == 0 and message.get("t") == "MESSAGE_CREATE":
                    item = to_relay(message.get("d") or {}, self.bot_id)
                    if item:
                        self.forwarder.send([item])
                elif op == 1:
                    ws.send(json.dumps({"op": 1, "d": self.sequence}))
                elif op in (7, 9):
                    return  # Reconnect / invalid session: start a fresh session.
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def run(self):
        delay = 1
        while not self.stop.is_set():
            try:
                self.session()
                delay = 1
            except Exception as error:  # noqa: BLE001
                _logger.warning("Gateway connection lost (%s); reconnecting in %ss.", type(error).__name__, delay)
                self.sleep(delay)
                delay = min(delay * 2, 60)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="the channel's inbound URL shown in Odoo")
    parser.add_argument("--bot", required=True, help="the bot's user ID shown in Odoo")
    args = parser.parse_args(argv)
    token, secret = os.environ.get("DISCORD_BOT_TOKEN"), os.environ.get("OMNI_RELAY_SECRET")
    if not token or not secret:
        parser.error("set DISCORD_BOT_TOKEN and OMNI_RELAY_SECRET in the environment")
    if not args.url.startswith("https://"):
        parser.error("--url must be the public HTTPS inbound URL")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Gateway(token, Forwarder(args.url, secret, args.bot), args.bot).run()


if __name__ == "__main__":
    main()
