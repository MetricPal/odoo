"""Loopback-only SMTP fixture; never forwards or stores mail outside memory."""

import socketserver
import threading
from contextlib import contextmanager


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        self.wfile.write(b'220 localhost test SMTP\r\n')
        while line := self.rfile.readline(8192):
            command = line.split(b' ', 1)[0].strip().upper()
            if command in (b'EHLO', b'HELO'):
                self.wfile.write(b'250 localhost\r\n')
            elif command == b'MAIL':
                self.server.envelopes.append(line.decode('ascii').strip())
                self.wfile.write(b'250 OK\r\n')
            elif command == b'RCPT':
                self.server.recipients.append(line.decode('ascii').strip())
                self.wfile.write(b'250 OK\r\n')
            elif command == b'DATA':
                self.wfile.write(b'354 End with dot\r\n')
                data = bytearray()
                while chunk := self.rfile.readline(8192):
                    if chunk == b'.\r\n':
                        break
                    if len(data) + len(chunk) > 1024 * 1024:
                        self.wfile.write(b'552 Test size limit\r\n')
                        return
                    data.extend(chunk[1:] if chunk.startswith(b'..') else chunk)
                if self.server.reject:
                    self.wfile.write(b'451 Synthetic SMTP rejection\r\n')
                else:
                    self.server.messages.append(bytes(data))
                    self.wfile.write(b'250 Accepted by local test sink\r\n')
            elif command == b'RSET':
                self.wfile.write(b'250 OK\r\n')
            elif command == b'QUIT':
                self.wfile.write(b'221 Bye\r\n')
                return
            else:
                self.wfile.write(b'502 Unsupported test command\r\n')


@contextmanager
def smtp_sink(*, reject=False):
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), SMTPHandler) as server:
        server.daemon_threads = True
        server.reject = reject
        server.messages = []
        server.envelopes = []
        server.recipients = []
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=3)
