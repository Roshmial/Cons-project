from __future__ import annotations

import http.server
import os
import socketserver
import urllib.error
import urllib.request
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_BASE = os.getenv("HERMES_WEB_FRONTEND_BACKEND_BASE", "http://127.0.0.1:8791").rstrip("/")
HOST = os.getenv("HERMES_WEB_FRONTEND_HOST", "127.0.0.1")
PORT = int(os.getenv("HERMES_WEB_FRONTEND_PORT", "8793"))


class FrontendProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy("GET")
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
            return
        self.send_error(405, "Method not allowed")

    def do_PATCH(self):
        if self.path.startswith("/api/"):
            self._proxy("PATCH")
            return
        self.send_error(405, "Method not allowed")

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
            return
        self.send_error(405, "Method not allowed")

    def do_OPTIONS(self):
        if self.path.startswith("/api/"):
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(405, "Method not allowed")

    def log_message(self, format: str, *args):
        super().log_message(format, *args)

    def _proxy(self, method: str):
        target = f"{BACKEND_BASE}{self.path}"
        body = None
        length = int(self.headers.get("Content-Length") or "0")
        if length:
            body = self.rfile.read(length)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "content-length"}}
        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() in {"transfer-encoding", "connection", "content-length"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in {"transfer-encoding", "connection", "content-length"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            message = f'{{"error":"frontend_proxy_error","detail":"{str(exc)}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ReusableTCPServer((HOST, PORT), FrontendProxyHandler) as httpd:
        print(f"Frontend proxy listening on http://{HOST}:{PORT} -> {BACKEND_BASE}")
        httpd.serve_forever()
