"""Audio Connector: whole phone calls the way Genesys Cloud makes them, without Genesys or Azure.

A small Genesys simulator opens the WebSocket, sends open/ping/dtmf/close and "audio", and reads
back what the bot says (FakeSpeech: see channels/audio_connector/speech.py).
"""
import asyncio
import json
import re
import unittest
import urllib.request
import uuid

try:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus
    from channels.audio_connector.call import Settings
    from channels.audio_connector.server import PATH, make_server
    from channels.audio_connector.speech import FakeSpeech
except ImportError:   # the voice extra is optional
    connect = None

from callcenter_bot import Bot, db

KEY = "test-key"
FAST = dict(silence_seconds=60, dtmf_seconds=0.3, frames_per_second=500, playback_wait_seconds=2)


class Genesys:
    """Plays the Genesys side of an Audio Connector session."""

    def __init__(self, ws):
        self.ws, self.seq, self.audio, self.messages, self.heard_upto = ws, 0, b"", [], 0
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for m in self.ws:
                if isinstance(m, bytes):
                    self.audio += m
                else:
                    self.messages.append(json.loads(m))
        except Exception:
            pass

    async def send(self, kind, **parameters):
        self.seq += 1
        await self.ws.send(json.dumps({"version": "2", "type": kind, "seq": self.seq, "id": "sess-1",
                                       "position": "PT1S", "parameters": parameters}))

    async def open(self, conversation=None, participant_id=None, channels=("external",)):
        await self.send("open", organizationId=str(uuid.uuid4()),
                        conversationId=conversation or str(uuid.uuid4()),
                        participant={"id": participant_id or str(uuid.uuid4()), "ani": "+66636538939",
                                     "dnis": "+6621234567"},
                        media=[{"type": "audio", "format": "PCMU", "channels": list(channels), "rate": 8000}])
        return await self.message("opened")

    async def say(self, text):            # the caller speaks
        await self.ws.send(b"SAY:" + text.encode())

    async def press(self, keys):           # the caller types on the keypad
        for k in keys:
            await self.send("dtmf", digit=k)

    def lines(self):
        return [m.group(1).decode() for m in re.finditer(rb"TTS:(.*?)\n", self.audio, re.S)]

    async def hear(self, timeout=5):
        """The next thing the bot says."""
        for _ in range(int(timeout / 0.02)):
            lines = self.lines()
            if len(lines) > self.heard_upto:
                self.heard_upto += 1
                return lines[self.heard_upto - 1]
            await asyncio.sleep(0.02)
        raise AssertionError(f"the bot said nothing new; so far: {self.lines()}")

    async def message(self, kind, timeout=5):
        for _ in range(int(timeout / 0.02)):
            for m in self.messages:
                if m["type"] == kind:
                    self.messages.remove(m)
                    return m
            await asyncio.sleep(0.02)
        raise AssertionError(f"no {kind!r} message; got {[m['type'] for m in self.messages]}")


@unittest.skipIf(connect is None, "pip install -r requirements-voice.txt")
class AudioConnectorTest(unittest.IsolatedAsyncioTestCase):
    async def start(self, speech=None, **settings):
        db.use_database(":memory:")
        self.server = await make_server(speech or FakeSpeech(), Bot(), KEY, "127.0.0.1", 0,
                                        Settings(**{**FAST, **settings})).__aenter__()
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}{PATH}"

    async def call(self, key=KEY):
        ws = await connect(self.url, additional_headers={"x-api-key": key})
        self.addAsyncCleanup(ws.close)
        return Genesys(ws)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_whole_call_balance_then_agent(self):
        await self.start()
        g = await self.call()
        opened = await g.open()
        self.assertEqual(opened["parameters"]["media"][0]["format"], "PCMU")
        greeting = await g.hear()
        self.assertTrue(greeting.startswith("สวัสดีค่ะ."), greeting)
        self.assertIn("มีอะไรให้ช่วยคะ", greeting)
        self.assertNotIn("เช่น", greeting)                              # no examples

        await g.say("อยากเช็คยอดค้างชำระครับ")
        asks_phone = await g.hear()
        self.assertIn("เบอร์โทรศัพท์", asks_phone)
        self.assertIn("พูดหรือกดตัวเลขก็ได้", asks_phone)          # keypad hint while a number is due

        await g.press("0636538939#")                              # typed on the keypad
        self.assertIn("4 ตัวท้าย", await g.hear())

        await g.say("แปด เก้า สาม เก้า")                           # spoken as words
        self.assertIn("520 บาท 75 สตางค์", await g.hear())

        await g.say("ขอคุยกับเจ้าหน้าที่ค่ะ")
        self.assertIn("โอนให้เจ้าหน้าที่", await g.hear())
        out = (await g.message("disconnect"))["parameters"]
        self.assertEqual(out["reason"], "completed")
        v = out["outputVariables"]
        self.assertEqual((v["intent"], v["handoffReason"], v["verifiedPhone"]),
                         ("live-agent-handoff", "agent", "0636538939"))
        self.assertEqual(v["topics"], "check_balance")
        self.assertEqual(v["ani"], "+66636538939")
        self.assertEqual(v["turns"], "4")

        await g.send("close", reason="end")                       # Genesys closes; we confirm
        closed = await g.message("closed")
        self.assertEqual(closed["parameters"]["outputVariables"]["intent"], "live-agent-handoff")

    async def test_keypad_without_hash_is_sent_after_a_pause(self):
        await self.start()
        g = await self.call()
        await g.open(); await g.hear()
        await g.say("ติดตามพัสดุ")
        await g.hear()
        await g.press("636538")                                   # no "#"
        self.assertIn("ไปรษณีย์ไทย", await g.hear())

    async def test_report_problem_ticket_goes_to_agent_data(self):
        await self.start()
        g = await self.call()
        await g.open(); await g.hear()
        await g.say("อินเทอร์เน็ตใช้ไม่ได้ตั้งแต่เช้าครับ")
        await g.hear()
        await g.say("ใช่ครับ")
        self.assertIn("ที เค, หนึ่ง ศูนย์ ศูนย์ หนึ่ง", await g.hear())   # ticket number read digit by digit
        await g.say("บายบาย")
        await g.hear()
        v = (await g.message("disconnect"))["parameters"]["outputVariables"]
        self.assertEqual((v["intent"], v["ticket"], v["topics"]), ("end-conversation", "TK1001", "report_problem,ticket_created"))

    async def test_silence_asks_then_hangs_up(self):
        await self.start(silence_seconds=0.6)
        g = await self.call()
        await g.open(); await g.hear()
        self.assertIn("ยังอยู่ในสายไหมคะ", await g.hear())
        self.assertIn("ขอวางสายก่อน", await g.hear())
        v = (await g.message("disconnect"))["parameters"]["outputVariables"]
        self.assertEqual(v["intent"], "no-response")

    async def test_caller_interrupts_the_bot(self):
        await self.start(FakeSpeech(seconds_per_char=0.05), frames_per_second=10)
        g = await self.call()
        await g.open()
        await asyncio.sleep(0.5)                                   # the long greeting is still playing
        await g.say("เช็คยอด")
        event = await g.message("event")
        self.assertEqual(event["parameters"]["entities"][0]["type"], "barge_in")

    async def test_caller_hangs_up(self):
        await self.start()
        g = await self.call()
        await g.open(); await g.hear()
        await g.say("เช็คยอด")
        await g.hear()
        await g.send("close", reason="disconnect")
        v = (await g.message("closed"))["parameters"]["outputVariables"]
        self.assertEqual(v["intent"], "caller-hung-up")
        self.assertEqual(v["topics"], "check_balance")

    async def test_ping_and_sequence_numbers(self):
        await self.start()
        g = await self.call()
        opened = await g.open()
        self.assertEqual((opened["seq"], opened["clientseq"], opened["id"]), (1, 1, "sess-1"))
        await g.send("ping")
        pong = await g.message("pong")
        self.assertEqual(pong["clientseq"], 2)

    async def test_probe_connection(self):
        await self.start()
        g = await self.call()
        zero = "00000000-0000-0000-0000-000000000000"
        opened = await g.open(conversation=zero, participant_id=zero)
        self.assertEqual(opened["parameters"]["media"], [])
        await asyncio.sleep(0.3)
        self.assertEqual(g.lines(), [])                            # no greeting on a probe

    async def test_stereo_audio_uses_the_caller_channel(self):
        await self.start()
        g = await self.call()
        await g.open(channels=("external", "internal")); await g.hear()
        caller = b"SAY:" + "เช็คยอด".encode()
        await g.ws.send(bytes(b for pair in zip(caller, b"\x00" * len(caller)) for b in pair))
        self.assertIn("เบอร์โทรศัพท์", await g.hear())

    async def test_connector_id_after_the_path(self):
        await self.start()
        ws = await connect(self.url + "/my-connector-id", additional_headers={"x-api-key": KEY})
        self.addAsyncCleanup(ws.close)
        g = Genesys(ws)
        await g.open()
        self.assertIn("สวัสดีค่ะ", await g.hear())

    async def test_tls_without_a_proxy(self):
        """wss:// served by the server itself, with a certificate."""
        import os, ssl, subprocess, tempfile
        from channels.audio_connector.server import tls_context
        folder = tempfile.mkdtemp()
        cert, key = os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem")
        try:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                            "-keyout", key, "-out", cert], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("openssl is needed to make a test certificate")
        db.use_database(":memory:")
        self.server = await make_server(FakeSpeech(), Bot(), KEY, "127.0.0.1", 0, Settings(**FAST),
                                        tls=tls_context(cert, key)).__aenter__()
        port = self.server.sockets[0].getsockname()[1]
        client = ssl.create_default_context(cafile=cert)       # trust our test certificate
        ws = await connect(f"wss://localhost:{port}{PATH}", ssl=client, additional_headers={"x-api-key": KEY})
        self.addAsyncCleanup(ws.close)
        g = Genesys(ws)
        await g.open()
        self.assertIn("สวัสดีค่ะ", await g.hear())

    async def test_voice_failure_hands_over(self):
        """A wrong Azure key means the bot cannot speak: the call goes to a person at once."""
        class BrokenVoice(FakeSpeech):
            async def synthesize(self, text):
                raise RuntimeError("Azure text-to-speech failed: 401 Unauthorized")
        await self.start(BrokenVoice())
        g = await self.call()
        with self.assertLogs("audio_connector", "ERROR") as logs:
            await g.open()
            v = (await g.message("disconnect"))["parameters"]["outputVariables"]
        self.assertEqual((v["intent"], v["handoffReason"]), ("live-agent-handoff", "speech_error"))
        self.assertIn("text-to-speech failed", logs.output[0])

    async def test_security_and_health(self):
        await self.start()
        with self.assertRaises(InvalidStatus) as e:
            await connect(self.url, additional_headers={"x-api-key": "wrong"})
        self.assertEqual(e.exception.response.status_code, 401)
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read())
        self.assertEqual(body, b"OK\n")


if __name__ == "__main__":
    unittest.main()
