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

APOLOGY = "ขออภัยค่ะ ระบบขัดข้องชั่วคราว ขอโอนสายให้เจ้าหน้าที่ดูแลต่อนะคะ"


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

    def handle(self, body: dict):
        """Returns (http_status, response_json)."""
        message = body.get("inputMessage")
        session_id = str(body.get("botSessionId") or "")[:256]
        if not isinstance(message, dict) or not session_id:
            return 400, {"error": "botSessionId and inputMessage are required"}
        params = body.get("parameters") or {}
        reply_format = str(params.get("replyFormat") or self.reply_format)
        key = "genesys:" + session_id
        text = str(message.get("text") or "")[:1000]
        try:
            if not text.strip() and key not in self.bot.sessions:
                reply = self.bot.welcome()            # first turn with no words yet: greet
            else:
                reply = self.bot.reply(key, text)
            session = self.bot.sessions.get(key)
            verified = session.verified_phone if session else None
        except Exception:
            log.exception("genesys session=%s: bot error", session_id[:8])
            return 200, _response(APOLOGY, "COMPLETE", INTENT_HANDOFF, {"handoffReason": "adapter_error"})

        say = reply.speech if reply_format == "speech" else reply.text
        log.info("genesys session=%s in=%r intent=%s handoff=%s end=%s", session_id[:8],
                 mask_digits(text), reply.intent, reply.handoff, reply.end)
        if reply.handoff:
            self.bot.reset(key)
            return 200, _response(say, "COMPLETE", INTENT_HANDOFF,
                                  {"handoffReason": reply.intent, "verifiedPhone": verified})
        if reply.end:
            return 200, _response(say, "COMPLETE", INTENT_END, {"verifiedPhone": verified})
        return 200, _response(say, "MOREDATA", INTENT_CONTINUE,
                              {"expectsDigits": "true" if reply.expects == "digits" else "false"})
