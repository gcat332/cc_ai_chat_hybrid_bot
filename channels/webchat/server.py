"""Web chat channel. Standard library only.

    python -m channels.webchat.server            # http://localhost:8000
    python -m channels.webchat.server --port 9000

API (the pages in static/ use it; your own website or app can call it too):
    POST /api/chat   {"session_id": "...", "message": "..."}  -> Reply as JSON
    POST /api/start  {"session_id": "..."}                    -> welcome Reply
    GET  /api/health                                         -> {"ok": true}

Admin page for the bank tables (customers, accounts, cards, loans, cases): /admin. All tables: python -m dataadmin
    Needs a password: set ADMIN_PASSWORD before starting. The browser asks for it
    (user name: admin). Without ADMIN_PASSWORD the admin page is switched off.
    GET  /api/admin/tables                                   -> all rows
    POST /api/admin/save    {"table", "row", "old_key"}       -> {"ok": true} or {"error": "..."}
    POST /api/admin/delete  {"table", "key"}                  -> {"ok": true}

Genesys Cloud (see channels/genesys/README.md), both need GENESYS_SECRET (sent by Genesys as a header):
    POST /api/genesys/botconnector  Bot Connector, messaging flows
    POST /api/genesys/turn          Data Action from a voice bot flow (channels/genesys/voice-bot-flow.md)

The tables are in data/callcenter.db (set CALLCENTER_DB to move it), created with demo rows
the first time.

Add --ai to answer questions the rules do not cover with Claude (see callcenter_bot/ai_fallback.py).
"""
import argparse
import base64
import hmac
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from callcenter_bot import Bot, admin, db
from callcenter_bot.privacy import mask_digits
from channels.genesys.connector import GenesysConnector

STATIC = Path(__file__).parent / "static"
PAGES = {"/": "index.html", "/index.html": "index.html", "/admin": "admin.html",
         "/admin.html": "admin.html", "/runtime.js": "runtime.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
MAX_MESSAGE_CHARS = 1000
log = logging.getLogger("webchat")
bot = Bot()
genesys = GenesysConnector(bot)


def admin_password():
    return os.environ.get("ADMIN_PASSWORD", "")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/health":
            return self._json(200, {"ok": True})
        if path.startswith("/admin") or path.startswith("/api/admin"):
            if not self._admin_ok():
                return
            if path == "/api/admin/tables":
                return self._json(200, db.all_tables())
        if path in PAGES:
            file = STATIC / PAGES[path]
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            return self._send(200, file.read_bytes(), TYPES[file.suffix], started=True)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(length, 64_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})

        if self.path in ("/api/genesys/botconnector", "/api/genesys/turn"):
            if not genesys.enabled:
                return self._json(503, {"error": "Genesys connector is off: set GENESYS_SECRET"})
            if not genesys.authorized(self.headers):
                log.warning("refused %s: %s", self.path, genesys.explain_refusal(self.headers))
                return self._json(403, {"error": "Forbidden"})
            if self.path == "/api/genesys/turn":     # Data Action from a voice bot flow
                status, result = genesys.handle_turn(body)
            else:                                    # Bot Connector (messaging flows)
                status, result = genesys.handle(body)
            return self._json(status, result)

        if self.path.startswith("/api/admin/"):
            if not self._admin_ok():
                return
            if self.path == "/api/admin/save":
                result = admin.save(str(body.get("table")), dict(body.get("row") or {}), body.get("old_key"))
            elif self.path == "/api/admin/delete":
                result = admin.delete(str(body.get("table")), body.get("key"))
            else:
                return self._json(404, {"error": "not found"})
            log.info("admin %s %s -> %s", self.path.rsplit("/", 1)[1], body.get("table"),
                     "ok" if result.get("ok") else "refused")
            return self._json(200 if result.get("ok") else 400, result)

        if self.path not in ("/api/chat", "/api/start"):
            return self._json(404, {"error": "not found"})
        session_id = str(body.get("session_id") or uuid.uuid4())[:64]
        if self.path == "/api/start":
            bot.reset(session_id)
            reply = bot.welcome()
        else:
            message = str(body.get("message", ""))[:MAX_MESSAGE_CHARS]
            reply = bot.reply(session_id, message)
            log.info("session=%s in=%r out_intent=%s handoff=%s", session_id[:8],
                     mask_digits(message), reply.intent, reply.handoff)
        if reply.handoff:
            # TODO: create a conversation in your live-agent system here
            # (e.g. LINE OA Chat, Zendesk, Freshchat, Genesys) and pass session_id.
            log.info("session=%s handed to a human agent", session_id[:8])
        self._json(200, {"session_id": session_id, **reply.to_dict()})

    def _admin_ok(self) -> bool:
        """HTTP Basic auth: user "admin", password ADMIN_PASSWORD. Sends the refusal itself."""
        password = admin_password()
        if not password:
            self._send(403, "หน้าจัดการข้อมูลปิดอยู่: ตั้งค่า ADMIN_PASSWORD แล้วเริ่มเซิร์ฟเวอร์ใหม่"
                       .encode("utf-8"), "text/plain; charset=utf-8")
            return False
        expected = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="callcenter-admin", charset="UTF-8"')
        self._send(401, "ต้องใส่รหัสผ่าน (ชื่อผู้ใช้: admin)".encode("utf-8"),
                   "text/plain; charset=utf-8", started=True)
        return False

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _send(self, status, payload: bytes, content_type: str, started: bool = False):
        if not started:
            self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # quieter than the default access log
        log.debug(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description="Thai call-center web chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ai", action="store_true",
                        help="answer questions the rules don't cover with Claude "
                             "(needs: pip install -r requirements-ai.txt, and ANTHROPIC_API_KEY)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    db.use_database(db.DEFAULT_PATH)
    print(f"Database: {db.DEFAULT_PATH}")
    global bot, genesys
    if args.ai:
        from callcenter_bot.ai_fallback import MODEL, make_claude_fallback
        bot = Bot(fallback=make_claude_fallback())
        genesys = GenesysConnector(bot)
        print(f"AI answers on ({MODEL}) for questions the rules don't cover")
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("Warning: ANTHROPIC_API_KEY is not set. Unless you signed in with `ant auth login`, "
                  "AI answers will fail and the bot will use its rules-only replies.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web chat on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    if genesys.enabled:
        print(f"Genesys Bot Connector on http://{args.host}:{args.port}/api/genesys/botconnector "
              f"(secret header: {genesys.secret_header})")
        print(f"Genesys Data Action (voice bot flow) on http://{args.host}:{args.port}/api/genesys/turn")
    if admin_password():
        print(f"Admin page on http://{args.host}:{args.port}/admin  (user: admin)")
    else:
        print("Admin page off: set ADMIN_PASSWORD to turn it on")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
