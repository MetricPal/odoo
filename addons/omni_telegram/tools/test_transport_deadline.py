"""Measure the real HTTP parser deadline using a local socket pair, without TLS or a provider."""

import importlib.util
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'providers' / filename)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


class TestDeadline(unittest.TestCase):
    def test_trickled_headers_are_stopped_by_total_deadline(self):
        # Load the two dependency-free modules without importing the Odoo addon.
        module('deadline_probe.secrets', 'secrets.py')
        transport = module('deadline_probe.transport', 'transport.py')
        client, peer = socket.socketpair()
        stopped = threading.Event()

        def trickle():
            try:
                peer.sendall(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                while not stopped.wait(.05):
                    peer.sendall(b'a')
            except OSError:
                pass

        thread = threading.Thread(target=trickle, daemon=True)
        connection = MagicMock()
        connection.sock = client
        connection.close.side_effect = client.close
        thread.start()
        start = time.monotonic()
        try:
            with (
                patch.dict(os.environ, {'OMNI_TELEGRAM_SANDBOX_NETWORK': '1'}),
                patch.object(transport, 'public_address', return_value=(2, ('149.154.167.220', 443))),
                patch.object(transport, 'PinnedHTTPSConnection', return_value=connection),
                self.assertRaises(transport.TelegramTransportError),
            ):
                transport.TelegramHTTP().call('12345:' + 'a' * 30, 'getMe', {})
            elapsed = time.monotonic() - start
            print(f'LOCAL_TRICKLE_DEADLINE_SECONDS={elapsed:.3f}')  # noqa: T201 - measured test evidence
            self.assertGreater(elapsed, 0.1)
            self.assertLess(elapsed, 28)
            connection.request.assert_called_once()
            connection.close.assert_called_once()
        finally:
            stopped.set()
            peer.close()
            client.close()
            thread.join(timeout=1)


if __name__ == '__main__':
    unittest.main()
