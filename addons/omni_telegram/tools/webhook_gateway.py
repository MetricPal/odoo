"""Temporary sandbox ingress; exposes only webhook POSTs and a static health check."""
import argparse
import http.client
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 1024 * 1024
ROUTE = re.compile(r'/omni/inbound/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token'


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, upstream_port):
        self.upstream_port = upstream_port
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Never log inbound paths, headers, bodies or exception contents.


class Handler(BaseHTTPRequestHandler):
    server_version = 'OmniSandbox'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(10)
        self.deadline = threading.Timer(30, self.expire)
        self.deadline.daemon = True
        self.deadline.start()

    def expire(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self.deadline.cancel()
        super().finish()

    def log_message(self, format, *args):
        pass

    def respond(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        self.respond(204 if self.path == '/healthz' else 404)

    def do_POST(self):
        if not ROUTE.fullmatch(self.path):
            self.respond(404)
            return
        lengths = self.headers.get_all('Content-Length', [])
        secrets = self.headers.get_all(SECRET_HEADER, [])
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,8}', lengths[0]):
            self.respond(400)
            return
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            self.respond(413)
            return
        if len(secrets) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secrets[0]):
            self.respond(403)
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self.respond(415)
            return
        upstream = http.client.HTTPConnection('127.0.0.1', self.server.upstream_port, timeout=15)
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                self.respond(400)
                return
            # New request: never forward cookies, authorization, query selectors,
            # proxy headers or user-supplied host. Odoo is bound to one database.
            upstream.request('POST', self.path, body=body, headers={
                'Content-Type': 'application/json', SECRET_HEADER: secrets[0],
                'Connection': 'close',
            })
            response = upstream.getresponse()
            status = response.status if response.status in (200, 400, 403, 404, 413, 429, 503) else 502
            self.respond(status)
        except (OSError, http.client.HTTPException):
            self.respond(503)
        finally:
            upstream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--upstream-port', type=int, default=8077)
    args = parser.parse_args()
    with Gateway(('127.0.0.1', args.port), args.upstream_port) as gateway:
        gateway.serve_forever()
