import io
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch

from webhook_gateway import MAX_BODY, SECRET_HEADER, Handler

PATH = '/omni/inbound/11111111-1111-4111-8111-111111111111'


class TestGateway(unittest.TestCase):
    def request(self, path=PATH, headers=None):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.headers = Message()
        for key, value in headers or []:
            handler.headers[key] = value
        handler.rfile = io.BytesIO(b'{}')
        handler.server = MagicMock(upstream_port=8077)
        handler.respond = MagicMock()
        return handler

    def valid_headers(self):
        return [('Content-Length', '2'), ('Content-Type', 'application/json'), (SECRET_HEADER, 'a' * 32)]

    def test_only_static_health_is_exposed_by_get(self):
        for path, status in [('/healthz', 204), ('/web/login', 404), ('/web/database/manager', 404), (PATH, 404)]:
            handler = self.request(path)
            handler.do_GET()
            handler.respond.assert_called_once_with(status)

    def test_non_webhook_and_query_paths_never_reach_odoo(self):
        for path in ['/web/login', '/jsonrpc', PATH + '?db=other', PATH + '/', '/omni/inbound/%2e%2e']:
            handler = self.request(path, self.valid_headers())
            with patch('webhook_gateway.http.client.HTTPConnection') as upstream:
                handler.do_POST()
                upstream.assert_not_called()
            handler.respond.assert_called_once_with(404)

    def test_bad_length_secret_and_chunked_requests_rejected(self):
        cases = [([], 400), ([('Content-Length', '2')], 403),
                 (self.valid_headers() + [('Content-Length', '2')], 400),
                 (self.valid_headers() + [('Transfer-Encoding', 'chunked')], 400),
                 (self.valid_headers() + [(SECRET_HEADER, 'b' * 32)], 403),
                 ([('Content-Length', str(MAX_BODY + 1))], 413)]
        for headers, status in cases:
            handler = self.request(headers=headers)
            with patch('webhook_gateway.http.client.HTTPConnection') as upstream:
                handler.do_POST()
                upstream.assert_not_called()
            handler.respond.assert_called_once_with(status)

    def test_forwarding_strips_sessions_host_and_database_headers(self):
        handler = self.request(headers=self.valid_headers() + [('Cookie', 'session_id=secret'),
            ('Authorization', 'Bearer secret'), ('Host', 'other.example'), ('X-Forwarded-Host', 'other.example')])
        with patch('webhook_gateway.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value.status = 200
            handler.do_POST()
            connection.assert_called_once_with('127.0.0.1', 8077, timeout=15)
            headers = connection.return_value.request.call_args.kwargs['headers']
            self.assertEqual(set(headers), {'Content-Type', SECRET_HEADER, 'Connection'})
            connection.return_value.close.assert_called_once()
        handler.respond.assert_called_once_with(200)

    def test_upstream_errors_are_sanitized(self):
        handler = self.request(headers=self.valid_headers())
        with patch('webhook_gateway.http.client.HTTPConnection') as connection:
            connection.return_value.request.side_effect = OSError('private upstream detail')
            handler.do_POST()
            connection.return_value.close.assert_called_once()
        handler.respond.assert_called_once_with(503)


if __name__ == '__main__':
    unittest.main()
