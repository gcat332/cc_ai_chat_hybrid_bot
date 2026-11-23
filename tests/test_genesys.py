"""Genesys Bot Connector: a whole call as Genesys would send it, without Genesys."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from callcenter_bot import Bot, db
from channels.genesys.connector import GenesysConnector


def turn(text, session="call-1", **params):
    body = {"botId": "d150eb60-f36e-4f4c-850d-9eb679cb5258", "botVersion": "1", "botSessionId": session,
            "inputMessage": {"type": "Text", "text": text}, "languageCode": "th-th",
            "botSessionTimeout": 3600, "genesysConversationId": "conv-1"}
    if params:
        body["parameters"] = params
    return body


class ConnectorTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")
        self.c = GenesysConnector(Bot(), secret="s3cret")

    def send(self, text, **kw):
        status, out = self.c.handle(turn(text, **kw))
        self.assertEqual(status, 200)
        return out

    def test_whole_call_with_the_test_number(self):
        out = self.send("")                                        # call starts, no words yet
        self.assertEqual(out["botState"], "MOREDATA")
        self.assertIn("สวัสดีค่ะ", out["replymessages"][0]["text"])

        out = self.send("อยากเช็คยอดค้างชำระครับ")
        self.assertEqual(out["parameters"]["expectsDigits"], "true")
        self.assertIn("เบอร์โทรศัพท์", out["replymessages"][0]["text"])

        out = self.send("ศูนย์หกสาม หกห้าสาม แปดเก้าสามเก้า")            # how speech recognition may write it
        self.assertIn("4 ตัวท้าย", out["replymessages"][0]["text"])

        out = self.send("8939")
        self.assertEqual(out["botState"], "MOREDATA")
        self.assertIn("520 บาท 75 สตางค์", out["replymessages"][0]["text"])

        out = self.send("ขอคุยกับเจ้าหน้าที่")
        self.assertEqual((out["botState"], out["intent"]), ("COMPLETE", "live-agent-handoff"))
        self.assertEqual(out["parameters"], {"handoffReason": "agent", "verifiedPhone": "0636538939"})

    def test_goodbye_ends_the_call(self):
        self.send("สวัสดี")
        out = self.send("บายบาย")
        self.assertEqual((out["botState"], out["intent"]), ("COMPLETE", "end-conversation"))

    def test_text_format_for_chat_flows(self):
        out = self.send("ติดตามพัสดุ 123456", replyFormat="text")
        self.assertIn("คำสั่งซื้อ 123456", out["replymessages"][0]["text"])   # as written, for a chat window
        self.assertIn("KEX0099887766", out["replymessages"][0]["text"])

    def test_speech_format_for_voice_flows(self):
        out = self.send("ติดตามพัสดุ 123456")
        self.assertIn("หนึ่ง สอง สาม, สี่ ห้า หก", out["replymessages"][0]["text"])  # digit by digit
        self.assertNotIn("KEX", out["replymessages"][0]["text"])   # long tracking code is not read out

    def test_sessions_are_separate(self):
        self.send("เช็คยอด", session="a")
        out = self.send("8939", session="b")       # session b never gave a phone number
        self.assertNotIn("520", out["replymessages"][0]["text"])

    def test_bad_request(self):
        self.assertEqual(self.c.handle({"botSessionId": "x"})[0], 400)

    def test_bot_error_hands_off_instead_of_failing(self):
        self.c.bot.reply = lambda *a: 1 / 0
        with self.assertLogs("genesys", "ERROR"):
            status, out = self.c.handle(turn("สวัสดี"))
        self.assertEqual((status, out["botState"], out["intent"]), (200, "COMPLETE", "live-agent-handoff"))
        self.assertEqual(out["parameters"]["handoffReason"], "adapter_error")

    def test_secret(self):
        self.assertTrue(self.c.authorized({"X-Bot-Secret": "s3cret"}))
        self.assertTrue(self.c.authorized({"x-bot-secret": "Bearer s3cret"}))
        self.assertFalse(self.c.authorized({"x-bot-secret": "nope"}))
        self.assertFalse(self.c.authorized({}))
        self.assertFalse(GenesysConnector(Bot(), secret="").authorized({"x-bot-secret": ""}))

    def test_refusal_is_explained_without_the_secret(self):
        why = self.c.explain_refusal({"Content-Type": "application/json"})
        self.assertIn("no x-bot-secret header", why)
        self.assertIn("content-type", why)
        why = self.c.explain_refusal({"x-bot-secret": "${credentials.secret}"})
        self.assertIn("unfilled template", why)
        why = self.c.explain_refusal({"x-bot-secret": "s3cret\n"})
        self.assertIn("line break", why)
        why = self.c.explain_refusal({"x-bot-secret": "s3crex"})
        self.assertIn("same length but different", why)
        for header in ("${credentials.secret}", "s3cret\n", "s3crex", "nope"):
            self.assertNotIn("s3cret", self.c.explain_refusal({"x-bot-secret": header}).replace(header, ""))


class DataActionTest(unittest.TestCase):
    """POST /api/genesys/turn: a voice bot flow sends the words Genesys recognised, speaks the reply."""

    def setUp(self):
        db.use_database(":memory:")
        self.c = GenesysConnector(Bot(), secret="s3cret")

    def say(self, text, session="conv-1", **kw):
        status, out = self.c.handle_turn({"sessionId": session, "text": text, **kw})
        self.assertEqual(status, 200)
        self.assertTrue(all(isinstance(v, str) for v in out.values()), out)   # flat strings for the translation map
        return out

    def test_whole_call_as_genesys_hears_it(self):
        out = self.say("")                                        # bot flow starts: greet
        self.assertIn("สวัสดีค่ะ", out["reply"])
        self.assertEqual(out["action"], "continue")
        out = self.say("เช็ค ยอด ทาง ชำระ")                         # how Thai Whisper heard "เช็คยอดค้างชำระ"
        self.assertEqual(out["expectsDigits"], "true")
        self.say("ศูนย์ หก สาม หก ห้า สาม แปด เก้า สาม เก้า")
        out = self.say("แปด เก้า สาม เก้า")
        self.assertIn("520 บาท 75 สตางค์", out["reply"])            # speech format: money worded for TTS
        self.assertEqual(out["verifiedPhone"], "0636538939")
        out = self.say("ขอคุยกับเจ้าหน้าที่")
        self.assertEqual((out["action"], out["handoffReason"], out["verifiedPhone"]),
                         ("handoff", "agent", "0636538939"))
        self.assertNotIn("genesys:conv-1", self.c.bot.sessions)   # handoff ends the bot session

    def test_goodbye_ends(self):
        self.say("")
        self.assertEqual(self.say("บายบาย")["action"], "end")

    def test_text_format(self):
        out = self.say("ติดตามพัสดุ 123456", format="text")
        self.assertIn("123456", out["reply"])

    def test_sessions_are_separate(self):
        self.say("เช็คยอด", session="a")
        self.assertNotIn("520", self.say("8939", session="b")["reply"])

    def test_bad_request_and_bot_error(self):
        self.assertEqual(self.c.handle_turn({"text": "hi"})[0], 400)
        self.c.bot.reply = lambda *a: 1 / 0
        with self.assertLogs("genesys", "ERROR"):
            out = self.say("สวัสดี")
        self.assertEqual((out["action"], out["handoffReason"]), ("handoff", "adapter_error"))


class ServerRouteTest(unittest.TestCase):
    """The real HTTP endpoint, as Genesys calls it."""

    def setUp(self):
        db.use_database(":memory:")
        from channels.webchat import server
        self.server_module = server
        self.saved = server.genesys
        server.genesys = GenesysConnector(server.bot, secret="s3cret")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/genesys/botconnector"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_module.genesys = self.saved

    def post(self, body, headers, url=None):
        req = urllib.request.Request(url or self.url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_endpoint(self):
        status, out = self.post(turn("เช็คยอด", session="http-1"), {"x-bot-secret": "s3cret"})
        self.assertEqual((status, out["botState"]), (200, "MOREDATA"))
        self.assertEqual(self.post(turn("เช็คยอด"), {"x-bot-secret": "wrong"})[0], 403)
        self.server_module.genesys = GenesysConnector(self.server_module.bot, secret="")
        self.assertEqual(self.post(turn("เช็คยอด"), {})[0], 503)

    def test_data_action_endpoint(self):
        url = self.url.replace("botconnector", "turn")
        body = {"sessionId": "http-2", "text": ""}
        status, out = self.post(body, {"x-bot-secret": "s3cret"}, url)
        self.assertEqual((status, out["action"]), (200, "continue"))
        self.assertIn("สวัสดีค่ะ", out["reply"])
        self.assertEqual(self.post(body, {"x-bot-secret": "wrong"}, url)[0], 403)


if __name__ == "__main__":
    unittest.main()
