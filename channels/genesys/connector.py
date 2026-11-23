"""Genesys Cloud Bot Connector for the Thai call-center bot (connector A).

Genesys Cloud runs the call or chat; this bot decides what to say. Each customer turn, Genesys
POSTs the customer's words to the "Bot Connector Handle Utterance URI" (this server's
/api/genesys/botconnector) and plays or shows the reply.

    customer ─► Genesys (Architect "Call Bot Connector") ─► POST /api/genesys/botconnector
                                                         ◄─ replymessages + botState + intent

Protocol: Genesys Bot Connector (v1) as used by Google's and other public adapters:
request  {botId, botVersion, botSessionId, inputMessage: {type: "Text", text}, languageCode,
          botSessionTimeout, genesysConversationId, parameters}
response {replymessages: [{type: "Text", text}], botState: MOREDATA | COMPLETE | FAILED,
          intent, confidence, parameters}

How our replies map:
  normal reply           -> MOREDATA, intent "continue" (Genesys says it, then sends the next words)
  ขอคุยกับเจ้าหน้าที่ etc. -> COMPLETE, intent "live-agent-handoff", slots handoffReason, verifiedPhone
                            (route this to a Transfer to ACD action in Architect)
  goodbye                -> COMPLETE, intent "end-conversation" (route to Disconnect)
  our own error          -> COMPLETE, intent "live-agent-handoff", handoffReason "adapter_error"
                            (Genesys treats a non-200 as a hard failure that can drop the customer)

Security: Genesys sends the integration's credential fields as request headers. Add a credential
field named like GENESYS_SECRET_HEADER (default "x-bot-secret") whose value is GENESYS_SECRET.
Without GENESYS_SECRET set, the connector refuses every request.
"""
import hmac
import logging
import os

from callcenter_bot import Bot
from callcenter_bot.privacy import mask_digits

INTENT_CONTINUE = "continue"
INTENT_HANDOFF = "live-agent-handoff"
INTENT_END = "end-conversation"
log = logging.getLogger("genesys")

APOLOGY = "ขออภัยค่ะ ระบบขัดข้อง ขอโอนให้เจ้าหน้าที่นะคะ"


def _response(text: str, state: str, intent: str, parameters: dict = None) -> dict:
    return {
        "replymessages": [{"type": "Text", "text": text}] if text else [],
        "botState": state,
        "intent": intent,
        "confidence": 1.0,
        "parameters": {k: str(v) for k, v in (parameters or {}).items() if v is not None},
    }


class GenesysConnector:
    def __init__(self, bot: Bot, secret: str = None, secret_header: str = None, reply_format: str = None):
        self.bot = bot
        self.secret = secret if secret is not None else os.environ.get("GENESYS_SECRET", "")
        self.secret_header = (secret_header or os.environ.get("GENESYS_SECRET_HEADER") or "x-bot-secret").lower()
        # "speech": numbers worded for text-to-speech (voice flows). "text": as written (chat flows).
        self.reply_format = reply_format or os.environ.get("GENESYS_REPLY_FORMAT", "speech")

    @property
    def enabled(self) -> bool:
        return bool(self.secret)

    def authorized(self, headers) -> bool:
        if not self.secret:
            return False
        received = next((v for k, v in headers.items() if k.lower() == self.secret_header), "")
        if received.lower().startswith("bearer "):
            received = received[7:]
        return hmac.compare_digest(received.encode(), self.secret.encode())

    def _turn(self, session_id: str, text: str):
        """One customer turn. Returns (reply, verified_phone). Raises on a bot error.
        Empty text on a new session greets the customer."""
        key = "genesys:" + session_id
        if not text.strip() and key not in self.bot.sessions:
            reply = self.bot.welcome()
        else:
            reply = self.bot.reply(key, text)
        session = self.bot.sessions.get(key)
        verified = session.verified_phone if session else None
        log.info("genesys session=%s in=%r intent=%s handoff=%s end=%s", session_id[:8],
                 mask_digits(text), reply.intent, reply.handoff, reply.end)
        if reply.handoff or reply.end:
            self.bot.reset(key)
        return reply, verified

    def explain_refusal(self, headers) -> str:
        """Why authorized() said no, for the log. Never includes the secret or what was received."""
        names = sorted(k.lower() for k in headers.keys())
        received = next((v for k, v in headers.items() if k.lower() == self.secret_header), None)
        if received is None:
            return f"no {self.secret_header} header (headers received: {', '.join(names)})"
        value = received[7:] if received.lower().startswith("bearer ") else received
        hints = []
        if "${" in value or "credentials." in value:
            hints.append("looks like an unfilled template: check the credential field name")
        if value != value.strip():
            hints.append("has spaces or a line break around it")
        if len(value.strip()) == len(self.secret) and value.strip() != self.secret:
            hints.append("same length but different value")
        return (f"{self.secret_header} does not match: received {len(value)} characters, expected "
                f"{len(self.secret)}" + (f" ({'; '.join(hints)})" if hints else ""))

    def handle(self, body: dict):
        """Bot Connector (messaging flows). Returns (http_status, response_json)."""
        message = body.get("inputMessage")
        session_id = str(body.get("botSessionId") or "")[:256]
        if not isinstance(message, dict) or not session_id:
            return 400, {"error": "botSessionId and inputMessage are required"}
        params = body.get("parameters") or {}
        reply_format = str(params.get("replyFormat") or self.reply_format)
        text = str(message.get("text") or "")[:1000]
        try:
            reply, verified = self._turn(session_id, text)
        except Exception:
            log.exception("genesys session=%s: bot error", session_id[:8])
            return 200, _response(APOLOGY, "COMPLETE", INTENT_HANDOFF, {"handoffReason": "adapter_error"})

        say = reply.speech if reply_format == "speech" else reply.text
        if reply.handoff:
            return 200, _response(say, "COMPLETE", INTENT_HANDOFF,
                                  {"handoffReason": reply.intent, "verifiedPhone": verified,
                                   "orderId": reply.context.get("order"), "ticket": reply.context.get("ticket")})
        if reply.end:
            return 200, _response(say, "COMPLETE", INTENT_END, {"verifiedPhone": verified})
        return 200, _response(say, "MOREDATA", INTENT_CONTINUE,
                              {"expectsDigits": "true" if reply.expects == "digits" else "false"})

    def handle_turn(self, body: dict):
        """Data Action (voice bot flows): Genesys recognises the caller's Thai, sends the words here,
        and speaks the reply with its own text-to-speech.

        request  {"sessionId": Session.ConversationId, "text": what the caller said ("" to start),
                  "format": "speech" (default) | "text"}
        response {"reply", "action": "continue" | "handoff" | "end", "handoffReason",
                  "verifiedPhone", "expectsDigits", "orderId", "ticket"}   all strings, flat
        Returns (http_status, response_json). Bot errors answer 200 + handoff, so the caller is not dropped.
        """
        session_id = str(body.get("sessionId") or "")[:256]
        if not session_id:
            return 400, {"error": "sessionId is required"}
        text = str(body.get("text") or "")[:1000]
        reply_format = str(body.get("format") or "speech")
        try:
            reply, verified = self._turn(session_id, text)
        except Exception:
            log.exception("genesys session=%s: bot error", session_id[:8])
            return 200, {"reply": APOLOGY, "action": "handoff", "handoffReason": "adapter_error",
                         "verifiedPhone": "", "expectsDigits": "false", "orderId": "", "ticket": ""}
        action = "handoff" if reply.handoff else "end" if reply.end else "continue"
        return 200, {
            "reply": reply.speech if reply_format == "speech" else reply.text,
            "action": action,
            "handoffReason": reply.intent if reply.handoff else "",
            "verifiedPhone": verified or "",
            "expectsDigits": "true" if reply.expects == "digits" else "false",
            "orderId": reply.context.get("order", ""),       # set on handoff: what the agent should see
            "ticket": reply.context.get("ticket", ""),
        }
