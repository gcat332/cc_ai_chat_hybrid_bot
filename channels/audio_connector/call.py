"""One phone call through the Genesys Audio Connector, driven by the same bot as the web chat.

    caller audio ─► speech recognition (Thai) ─► Bot.reply ─► Thai voice ─► caller
    keypad (DTMF) ──────────────────────────────┘

Like the web page's call mode:
- greets and reads the menu, then talks back and forth with no buttons
- the caller can interrupt (barge-in): the bot stops talking at once
- numbers can be spoken or typed on the keypad, ending with # (or a short pause)
- silence: "ยังอยู่ในสายไหม", then a polite goodbye
- a request for a person, failed ID checks or goodbye end the bot part with a "disconnect" whose
  outputVariables tell Architect what to do next (transfer to a queue, or hang up) and what the
  agent should see (verified phone, ticket, topics)
"""
import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass

from callcenter_bot import Bot, config
from callcenter_bot.privacy import mask_digits
from callcenter_bot.thai_format import speech_text

from . import protocol

log = logging.getLogger("audio_connector")
P, Q = config.STATEMENT_PARTICLE, config.QUESTION_PARTICLE
TOPICS = {"check_balance", "order_status", "report_problem", "ticket_created", "payment_channels", "hours"}


@dataclass
class Settings:
    silence_seconds: float = 8.0       # quiet this long after the bot finished: ask "still there?"
    dtmf_seconds: float = 2.5          # keypad digits are sent after this pause, or at once with #
    frames_per_second: float = 10.0    # Genesys rate limit: stay at or under ~10 audio frames/s
    playback_wait_seconds: float = 20.0  # longest wait for the last words before disconnecting


def _say(text: str) -> str:
    return speech_text(text, config.SAY_AS, keep_together=(config.BRAND,))


class CallSession:
    def __init__(self, connection, speech, bot: Bot, settings: Settings = None):
        self.ws = connection
        self.speech = speech
        self.bot = bot
        self.settings = settings or Settings()
        self.proto = protocol.Protocol()
        self.loop = asyncio.get_running_loop()
        self.key = None
        self.stereo = False
        self.recognizer = None
        self.running = True
        self.disconnecting = False
        self.paused = False
        self.audio = deque()                 # bot audio frames not yet sent
        self.playback_end = 0.0              # monotonic time the caller will have heard it all
        self.inputs = asyncio.Queue()        # what the caller said or typed, in order
        self.busy = False                    # a turn is being answered
        self.last_activity = time.monotonic()
        self.silences = 0
        self.dtmf = ""
        self.dtmf_task = None
        self.tasks = []
        # What Architect gets back
        self.outcome = {"intent": "", "handoffReason": "", "verifiedPhone": "", "ticket": "",
                        "topics": "", "lastCustomerText": "", "turns": "0", "ani": ""}
        self.topics = []

    # ---- main loop --------------------------------------------------------------------------
    async def run(self):
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    self._on_audio(message)
                else:
                    await self._on_message(json.loads(message))
                if not self.running:
                    break
        except Exception as e:   # a dropped connection ends the call quietly
            log.info("call %s: connection ended (%s: %s)", self._tag(), type(e).__name__, e)
        finally:
            await self._stop()

    async def _on_message(self, msg: dict):
        self.proto.received(msg)
        kind = msg.get("type")
        if kind == "open":
            await self._on_open(msg)
        elif kind == "ping":
            await self._send(self.proto.pong())
        elif kind == "close":
            log.info("call %s: Genesys closed (%s)", self._tag(), msg.get("parameters", {}).get("reason"))
            self._finish_outcome()
            await self._send(self.proto.closed(self.outcome))
            self.running = False
        elif kind == "dtmf":
            self._on_digit(str(msg.get("parameters", {}).get("digit", "")))
        elif kind == "paused":
            self.paused = True
        elif kind == "resumed":
            self.paused = False
            self.last_activity = time.monotonic()
        elif kind == "error":
            log.warning("call %s: Genesys error %s", self._tag(), msg.get("parameters"))

    async def _on_open(self, msg: dict):
        if protocol.is_probe(msg):          # Genesys checking the connection: no call
            await self._send(self.proto.opened([]))
            log.info("probe connection answered")
            return
        params = msg.get("parameters", {})
        media, self.stereo = protocol.choose_media(params.get("media"))
        if not media:
            await self._send(self.proto.disconnect("error", "PCMU 8 kHz audio is required"))
            self.running = False
            return
        await self._send(self.proto.opened([media]))
        self.key = "genesys-call:" + str(params.get("conversationId") or self.proto.session_id)
        self.outcome["ani"] = (params.get("participant") or {}).get("ani", "")
        log.info("call %s: opened", self._tag())
        self.recognizer = self.speech.make_recognizer(self.loop, self._on_speech)
        self.tasks = [asyncio.create_task(t) for t in (self._send_audio(), self._answer_turns(), self._watch_silence())]
        try:
            await self._speak(self.bot.welcome().speech)
        except Exception as e:   # e.g. a wrong Azure key: nothing can be said, so hand the call to a person
            log.error("call %s: text-to-speech failed, handing over: %s", self._tag(), e)
            self.disconnecting = True
            self.outcome.update(intent="live-agent-handoff", handoffReason="speech_error")
            self._finish_outcome()
            await self._send(self.proto.disconnect("completed", "speech_error", self.outcome))

    # ---- caller input -----------------------------------------------------------------------
    def _on_audio(self, frame: bytes):
        if self.recognizer and not self.paused and not self.disconnecting:
            self.recognizer.push(protocol.caller_audio(frame, self.stereo))

    def _on_speech(self, kind: str, text: str):
        if kind == "error":
            log.error("call %s: speech recognition error: %s", self._tag(), text)
            if not self.disconnecting:
                asyncio.create_task(self._end("live-agent-handoff", "speech_error", speak=
                                              f"ขออภัย{P} ระบบขัดข้อง ขอโอนให้เจ้าหน้าที่นะ{Q}"))
            return
        self.last_activity = time.monotonic()
        if self.disconnecting:
            return
        if kind == "partial" and len(text.strip()) >= 2:
            self._barge_in()
        elif kind == "final" and text.strip():
            self._barge_in()
            self.inputs.put_nowait(text.strip())

    def _on_digit(self, digit: str):
        if not digit or self.disconnecting:
            return
        self.last_activity = time.monotonic()
        self._barge_in()
        if self.dtmf_task:
            self.dtmf_task.cancel()
        if digit == "#":
            self._submit_digits()
        elif digit == "*":
            self.dtmf = ""
        else:
            self.dtmf += digit
            self.dtmf_task = asyncio.create_task(self._digits_after_pause())

    async def _digits_after_pause(self):
        await asyncio.sleep(self.settings.dtmf_seconds)
        self._submit_digits()

    def _submit_digits(self):
        if self.dtmf:
            self.inputs.put_nowait(self.dtmf)
            self.dtmf = ""

    def _barge_in(self):
        """The caller started talking or typing: stop the bot's voice now."""
        if self._playback_remaining() > 0.3:
            self.audio.clear()
            self.playback_end = time.monotonic()
            asyncio.create_task(self._send(self.proto.barge_in()))

    # ---- answering --------------------------------------------------------------------------
    async def _answer_turns(self):
        while self.running:
            text = await self.inputs.get()
            if self.disconnecting:
                continue
            self.busy = True
            self.silences = 0
            try:
                # The bot may call an AI fallback (slow): keep the call's loop free meanwhile.
                reply = await self.loop.run_in_executor(None, self.bot.reply, self.key, text)
                self._note(text, reply)
                speech = reply.speech
                if reply.expects == "digits":
                    speech += _say(f" พูดหรือกดตัวเลขก็ได้{P}")
                if reply.handoff:
                    await self._end("live-agent-handoff", reply.intent, speak=speech)
                elif reply.end:
                    await self._end("end-conversation", "", speak=speech)
                else:
                    await self._speak(speech)
            except Exception:
                log.exception("call %s: turn failed", self._tag())
                await self._end("live-agent-handoff", "adapter_error",
                                speak=f"ขออภัย{P} ระบบขัดข้อง ขอโอนให้เจ้าหน้าที่นะ{Q}")
            finally:
                self.busy = False
                self.last_activity = time.monotonic()

    def _note(self, text: str, reply):
        log.info("call %s: in=%r intent=%s", self._tag(), mask_digits(text), reply.intent)
        self.outcome["turns"] = str(int(self.outcome["turns"]) + 1)
        self.outcome["lastCustomerText"] = mask_digits(text)
        session = self.bot.sessions.get(self.key)
        if session and session.verified_phone:
            self.outcome["verifiedPhone"] = session.verified_phone
        ticket = re.search(r"TK\d+", reply.text)
        if reply.intent == "ticket_created" and ticket:
            self.outcome["ticket"] = ticket.group()
        if reply.intent in TOPICS and reply.intent not in self.topics:
            self.topics.append(reply.intent)

    # ---- speaking ---------------------------------------------------------------------------
    async def _speak(self, text: str):
        audio = await self.speech.synthesize(text)
        for i in range(0, len(audio), protocol.FRAME_BYTES):
            self.audio.append(audio[i:i + protocol.FRAME_BYTES])
        if not self.playback_end or self.playback_end < time.monotonic():
            self.playback_end = time.monotonic()

    async def _send_audio(self):
        """Sends bot audio at up to `frames_per_second` (Genesys plays it at its own pace)."""
        gap = 1.0 / self.settings.frames_per_second
        while self.running:
            if not self.audio or self.paused:
                await asyncio.sleep(0.02)
                continue
            frame = self.audio.popleft()
            try:
                await self.ws.send(frame)
            except Exception:
                self.running = False
                return
            now = time.monotonic()
            self.playback_end = max(now, self.playback_end) + len(frame) / protocol.BYTES_PER_SECOND
            await asyncio.sleep(gap)

    def _playback_remaining(self) -> float:
        queued = sum(len(f) for f in self.audio) / protocol.BYTES_PER_SECOND
        return queued + max(0.0, self.playback_end - time.monotonic())

    # ---- silence ----------------------------------------------------------------------------
    async def _watch_silence(self):
        while self.running and not self.disconnecting:
            await asyncio.sleep(0.25)
            if self.busy or self.dtmf or not self.inputs.empty() or self.paused:
                continue
            if self._playback_remaining() > 0:
                self.last_activity = time.monotonic()
                continue
            if time.monotonic() - self.last_activity < self.settings.silence_seconds:
                continue
            self.silences += 1
            self.last_activity = time.monotonic()
            if self.silences == 1:
                await self._speak(_say(f"ยังอยู่ในสายไหม{Q}"))
            else:
                await self._end("no-response", "", speak=_say(f"ไม่ได้ยินเสียงเลย ขอวางสายก่อนนะ{Q} ขอบคุณ{P}"))

    # ---- ending -----------------------------------------------------------------------------
    async def _end(self, intent: str, reason: str, speak: str = ""):
        """Say the last words, wait until the caller heard them, then hand the call back to Architect."""
        if self.disconnecting:
            return
        self.disconnecting = True
        self.outcome["intent"] = intent
        self.outcome["handoffReason"] = reason or ""
        if speak:
            try:
                await self._speak(speak)
            except Exception:
                log.exception("call %s: could not speak the last words", self._tag())
        deadline = time.monotonic() + self.settings.playback_wait_seconds
        while self._playback_remaining() > 0.05 and time.monotonic() < deadline and self.running:
            await asyncio.sleep(0.05)
        self._finish_outcome()
        log.info("call %s: disconnect intent=%s reason=%s", self._tag(), intent, reason)
        await self._send(self.proto.disconnect("completed", intent, self.outcome))

    def _finish_outcome(self):
        self.outcome["topics"] = ",".join(self.topics)
        if not self.outcome["intent"]:
            self.outcome["intent"] = "caller-hung-up"

    async def _send(self, text: str):
        try:
            await self.ws.send(text)
        except Exception:
            self.running = False

    async def _stop(self):
        self.running = False
        for task in self.tasks + ([self.dtmf_task] if self.dtmf_task else []):
            task.cancel()
        if self.recognizer:
            self.recognizer.close()
        if self.key:
            self.bot.reset(self.key)

    def _tag(self) -> str:
        return (self.proto.session_id or "-")[:8]
