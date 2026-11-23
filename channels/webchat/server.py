"""Web chat channel (phase 1). Standard library only.

    python -m channels.webchat.server            # http://localhost:8000
    python -m channels.webchat.server --port 9000

API (the page in static/ uses it; your own website or app can call it too):
    POST /api/chat   {"session_id": "...", "message": "..."}  -> Reply as JSON
    POST /api/start  {"session_id": "..."}                    -> welcome Reply
    GET  /api/health                                         -> {"ok": true}

Add --ai to answer questions the rules do not cover with Claude (see callcenter_bot/ai_fallback.py).
"""
import argparse
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from callcenter_bot import Bot
from callcenter_bot.privacy import mask_digits

STATIC = Path(__file__).parent / "static"
MAX_MESSAGE_CHARS = 1000
log = logging.getLogger("webchat")
bot = Bot()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/health":
            return self._json(200, {"ok": True})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/api/chat", "/api/start"):
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(length, 16_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})

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

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _send(self, status, payload: bytes, content_type: str):
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
    global bot
    if args.ai:
        from callcenter_bot.ai_fallback import MODEL, make_claude_fallback
        bot = Bot(fallback=make_claude_fallback())
        print(f"AI answers on ({MODEL}) for questions the rules don't cover")
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("Warning: ANTHROPIC_API_KEY is not set. Unless you signed in with `ant auth login`, "
                  "AI answers will fail and the bot will use its rules-only replies.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web chat on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
