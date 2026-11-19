"""Check the CASSIE session's readiness contract against a real HTTP server."""
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"session"))
import session


@pytest.mark.parametrize("code,ctype,body,expected", [
    (200, "application/json; charset=utf-8", b'{"service":"cassie-os"}', True),
    (200, "application/json", b'{"service":"another-service"}', False),
    (200, "text/html", b'<html>Captive portal</html>', False),
    (301, "application/json", b'{"service":"cassie-os"}', False),
    (200, "application/json", b'{"service":"cassie-os"}'+b' '*257, False),
    (200, "application/json", b'{invalid JSON', False),
])
def test_session_only_launches_for_expected_service(monkeypatch, code, ctype, body, expected):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/health"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

    http = HTTPServer(("127.0.0.1", 0), Handler)
    connect = http_client_connection
    monkeypatch.setattr(session.http.client, "HTTPConnection",
                        lambda host, port, timeout: connect(host, http.server_port, timeout=timeout))
    thread = threading.Thread(target=http.handle_request)
    thread.start()
    try:
        assert session.app_ready() is expected
    finally:
        thread.join(2)
        http.server_close()


http_client_connection = http.client.HTTPConnection
