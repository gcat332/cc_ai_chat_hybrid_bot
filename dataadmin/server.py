"""Mock-data page for the POC: view and edit every table of the bot's SQLite database.

    python -m dataadmin                  # http://127.0.0.1:8100
    python -m dataadmin --port 8200

It edits the same database file as the web chat and the Genesys endpoint (data/callcenter.db, or
CALLCENTER_DB), so the bot answers with a change straight away. Plain Python, nothing to install.

For your own machine only: it listens on 127.0.0.1. To open it to others (--host 0.0.0.0), set
ADMIN_PASSWORD; the browser then asks for user "admin" and that password.
"""
import argparse
import base64
import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from callcenter_bot import db

from . import store

PAGE = Path(__file__).parent / "static" / "index.html"
log = logging.getLogger("dataadmin")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class Handler(BaseHTTPRequestHandler):
    password = ""   # set from ADMIN_PASSWORD by main()

    def do_GET(self):
        if not self._allowed():
            return
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/tables":
            return self._json(200, {"tables": store.snapshot(), "database": db.DEFAULT_PATH})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(length, 256_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        try:
            if self.path == "/api/save":
                key = store.save(str(body.get("table")), dict(body.get("row") or {}), body.get("key"))
                log.info("saved %s %s", body.get("table"), key)
                return self._json(200, {"ok": True, "key": key})
            if self.path == "/api/delete":
                store.delete(str(body.get("table")), body.get("key"))
                log.info("deleted %s %s", body.get("table"), body.get("key"))
                return self._json(200, {"ok": True})
            if self.path == "/api/reset":
                store.reset()
                log.info("reset to the demo rows")
                return self._json(200, {"ok": True})
        except store.Refused as e:
            return self._json(400, {"error": str(e)})
        self._json(404, {"error": "not found"})

    def _allowed(self) -> bool:
        if not self.password:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, given = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                user, given = "", ""
            if user == "admin" and hmac.compare_digest(given.encode(), self.password.encode()):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="mock data", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def _send(self, status, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):   # quiet: actions are logged above
        pass


def main():
    parser = argparse.ArgumentParser(description="Mock-data page for the call-center bot's SQLite tables")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    Handler.password = os.environ.get("ADMIN_PASSWORD", "")
    if args.host not in LOCAL_HOSTS and not Handler.password:
        parser.error("set ADMIN_PASSWORD before opening the page to other machines (--host)")
    db.use_database(db.DEFAULT_PATH)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock data on http://{args.host}:{args.port}  (database: {db.DEFAULT_PATH}, Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
