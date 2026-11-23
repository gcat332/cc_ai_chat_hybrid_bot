"""Genesys Bot Connector: a whole call as Genesys would send it, without Genesys."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from callcenter_bot import Bot, config, db

# Agent hours are tested in test_bot.RequestTest; here a handoff must work at any time of day.
config.AGENT_HOURS = None
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
        self.assertIn("สวัสดีครับ", out["replymessages"][0]["text"])

        out = self.send("อยากทราบยอดค้างชำระครับ")
        self.assertEqual(out["parameters"]["expectsDigits"], "true")
        self.assertIn("เลขบัตรประชาชน 13 หลัก", out["replymessages"][0]["text"])

        out = self.send("1 5099 00543 21 5")                     # how speech recognition may write it
        self.assertEqual(out["botState"], "MOREDATA")
        self.assertIn("520 บาท 75 สตางค์", out["replymessages"][0]["text"])

        out = self.send("ขอคุยกับเจ้าหน้าที่")
        self.assertEqual((out["botState"], out["intent"]), ("COMPLETE", "live-agent-handoff"))
        self.assertEqual(out["parameters"], {"handoffReason": "agent", "verifiedPhone": "+66636538939",
                                             "customerName": "นายทดสอบ ระบบ",
                                             "summary": "ยืนยันตัวตนแล้ว (เลขบัตรประชาชน 13 หลัก) | ถามเรื่อง: ยอดค้างชำระ",
                                             "topic": "credit_card", "identify_type": "national_id",
                                             "kyc_result": "pass"})

    def test_goodbye_ends_the_call(self):
        self.send("สวัสดี")
        out = self.send("บายบาย")
        self.assertEqual((out["botState"], out["intent"]), ("COMPLETE", "end-conversation"))

    def test_text_format_for_chat_flows(self):
        self.send("ยอดเงินในบัญชี", replyFormat="text")
        out = self.send("3294367792962", replyFormat="text")
        self.assertIn("ลงท้าย 7890 คงเหลือ 85,420.50 บาท", out["replymessages"][0]["text"])  # as written

    def test_speech_format_for_voice_flows(self):
        self.send("ยอดเงินในบัญชี")
        out = self.send("3294367792962")
        self.assertIn("ลงท้าย เจ็ด แปด เก้า ศูนย์", out["replymessages"][0]["text"])  # digit by digit
        self.assertIn("85420 บาท 50 สตางค์", out["replymessages"][0]["text"])

    def test_sessions_are_separate(self):
        self.send("ยอดค้างชำระ", session="a")
        out = self.send("1509900543215", session="b")       # session b was never asked
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
        self.assertIn("สวัสดีครับ", out["reply"])
        self.assertEqual(out["action"], "continue")
        out = self.say("ยอด ค้าง ชำระ")                             # Genesys splits words with spaces
        self.assertEqual(out["expectsDigits"], "true")
        out = self.say("1509900543215")
        self.assertIn("520 บาท 75 สตางค์", out["reply"])            # speech format: money worded for TTS
        self.assertEqual(out["verifiedPhone"], "+66636538939")
        out = self.say("ขอคุยกับเจ้าหน้าที่")
        self.assertEqual((out["action"], out["handoffReason"], out["verifiedPhone"], out["customerName"]),
                         ("handoff", "agent", "+66636538939", "นายทดสอบ ระบบ"))
        self.assertNotIn("genesys:conv-1", self.c.bot.sessions)   # handoff ends the bot session

    def test_sample_call_close_home_loan(self):
        """The sample script: close a home loan, ask for details first, verify, transfer."""
        self.say("")
        self.assertIn("ใช่ไหมครับ", self.say("ต้องการปิดบัญชีสินเชื่อบ้านค่ะ")["reply"])
        self.assertIn("สอบถามรายละเอียด", self.say("ใช่ค่ะ")["reply"])
        out = self.say("ต้องการทราบรายละเอียดก่อนค่ะ ว่าต้องดำเนินการอย่างไรบ้าง")
        self.assertIn("ย้ายไปธนาคารอื่น", out["reply"])
        self.say("ย้ายไปธนาคารอื่นค่ะ ดอกถูกกว่า")
        self.say("ธนาคารบีให้ 3.25 เปอร์เซ็นต์ค่ะ")
        out = self.say("ภายใน 30 วันค่ะ")
        self.assertIn("เลขบัตรประชาชน", out["reply"])
        out = self.say("3294367792962")
        self.assertEqual((out["action"], out["handoffReason"]), ("handoff", "loan_refinance"))
        self.assertEqual(out["requestDetail"], "ปิดบัญชีสินเชื่อบ้านเพื่อรีไฟแนนซ์ (สอบถามรายละเอียดก่อน)")
        self.assertEqual(out["closeReason"], "รีไฟแนนซ์ไปธนาคารอื่น (ธนาคาร B)")
        self.assertTrue(out["loanDetail"].startswith("สินเชื่อบ้าน ลงท้าย 4567 คงเหลือ 2,350,000 บาท"))
        self.assertEqual((out["customerName"], out["verifiedPhone"]), ("นางสาวพลอยใส ใจดี", "+66815493626"))
        self.assertIn("แนะนำทางเลือกที่เหมาะสม", out["reply"])

    def test_caller_number_and_transcript(self):
        """Call.Ani from Genesys: 4 ID digits are enough; on handoff Genesys gets a summary and the
        transcript (Genesys, not this server, carries them on to ServiceNow)."""
        out = self.say("", session="conv-77", ani="tel:+66815493626")
        out = self.say("ต้องการปิดบัญชีสินเชื่อบ้าน", session="conv-77")
        self.say("ใช่", session="conv-77")
        self.say("สอบถามรายละเอียดก่อน", session="conv-77")
        self.say("ปิดยอดเองครับ มีเงินก้อน", session="conv-77")
        out = self.say("ภายใน 5 วัน", session="conv-77")
        self.assertIn("เรื่องเร่งด่วน", out["reply"])
        self.assertIn("4 ตัวท้าย", out["reply"])
        out = self.say("2962", session="conv-77")
        self.assertEqual((out["action"], out["customerName"]), ("handoff", "นางสาวพลอยใส ใจดี"))
        self.assertEqual(out["summary"], "ยืนยันตัวตนแล้ว (เบอร์ที่โทรเข้า + เลขบัตร 4 ตัวท้าย) | "
                                         "ต้องการ: ปิดบัญชีสินเชื่อบ้าน (สอบถามรายละเอียดก่อน) | "
                                         "เหตุผล: ปิดยอดด้วยเงินตัวเอง | สินเชื่อ: สินเชื่อบ้าน ลงท้าย 4567 คงเหลือ "
                                         "2,350,000 บาท ดอกเบี้ย 5.25% ค่างวด 18,500 บาท เหลือ 214 งวด")
        self.assertLessEqual(len(out["transcript"]), 500)
        self.assertTrue(out["transcript"].startswith("…"))         # cut to 500: the latest lines are kept
        self.assertIn("ลูกค้า: ภายใน 5 วัน", out["transcript"])
        self.assertIn("ลูกค้า: xxxx", out["transcript"])            # the 4 digits never shown
        self.assertIn("เรื่องเร่งด่วนครับ ขอเลขบัตรประชาชน 4 ตัวท้าย", out["transcript"])

    def test_goodbye_ends(self):
        self.say("")
        self.assertEqual(self.say("บายบาย")["action"], "end")

    def test_text_format(self):
        self.say("บัตรเครดิต วงเงินเหลือเท่าไหร่", format="text")
        out = self.say("3294367792962", format="text")
        self.assertIn("ลงท้าย 7788", out["reply"])

    def test_sessions_are_separate(self):
        self.say("ยอดค้างชำระ", session="a")
        self.assertNotIn("520", self.say("1509900543215", session="b")["reply"])

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
        self.assertIn("สวัสดีครับ", out["reply"])
        self.assertEqual(self.post(body, {"x-bot-secret": "wrong"}, url)[0], 403)


if __name__ == "__main__":
    unittest.main()


class PayOffScenarioTest(unittest.TestCase):
    """The KTB PayOff PoC's six ServiceNow scenarios (C1..C6): same callers (ANI), loans and amounts as
    ServiceNow's Core Banking mock, and the participant data ServiceNow's PayOff flow reads."""

    def setUp(self):
        db.use_database(":memory:")
        self.c = GenesysConnector(Bot(), secret="s3cret")

    def call(self, n, *lines):
        """Scenario n calls from +6681000000n; returns the last answer."""
        sid, ani = f"payoff-c{n}", f"tel:+6681000000{n}"
        out = None
        for text in ("",) + lines:
            status, out = self.c.handle_turn({"sessionId": sid, "text": text, "ani": ani})
            self.assertEqual(status, 200)
            self.assertTrue(all(isinstance(v, str) for v in out.values()), out)
        return out

    def test_c2_standard_refinance(self):
        out = self.call(2, "อยากปิดยอดสินเชื่อบ้านก่อนกำหนดครับ", "ใช่ครับ", "ปิดเลยครับ",
                        "จะรีไฟแนนซ์ไปธนาคารบีครับ", "สามจุดสองห้าเปอร์เซ็นต์ โปรสองปี เงินคืนห้าพันบาท",
                        "ภายใน 30 วัน")
        self.assertIn("4 ตัวท้าย", out["reply"])                  # calling from the registered number
        out = self.call(2, "0029")
        self.assertEqual(out["action"], "handoff")
        self.assertEqual({k: out[k] for k in ("verifiedPhone", "customerName", "topic", "identify_type",
                                               "kyc_result", "loan_number", "reason", "closing_within_days",
                                               "new_bank_name", "new_interest_rate", "promotion_period_months",
                                               "cashback_offered")},
                         {"verifiedPhone": "+66810000002", "customerName": "สมหญิง ทดสอบ", "topic": "payoff",
                          "identify_type": "national_id", "kyc_result": "pass", "loan_number": "PHL-LN-0002",
                          "reason": "refinance", "closing_within_days": "30", "new_bank_name": "ธนาคาร B",
                          "new_interest_rate": "3.25", "promotion_period_months": "24", "cashback_offered": "5000"})
        self.assertIn("สินเชื่อบ้าน ลงท้าย 0002 คงเหลือ 800,000 บาท ดอกเบี้ย 5.5%", out["summary"])

    def test_c1_urgent(self):
        out = self.call(1, "ต้องปิดสินเชื่อบ้านภายในห้าวันครับ", "ใช่", "ปิดเลย", "ปิดยอดเองครับ")
        self.assertIn("เรื่องเร่งด่วน", out["reply"])            # within 5 days: no "how soon" question
        out = self.call(1, "0011")
        self.assertEqual((out["topic"], out["loan_number"], out["closing_within_days"], out["reason"]),
                         ("payoff", "PHL-LN-0001", "5", "own_funds"))

    def test_c3_vip(self):
        out = self.call(3, "รีไฟแนนซ์บ้านครับ", "ใช่", "สอบถามรายละเอียดก่อน", "ยังไม่ทราบ", "ไม่รีบ", "0037")
        self.assertEqual((out["action"], out["customerName"], out["loan_number"], out["closing_within_days"]),
                         ("handoff", "วิชัย ทดสอบ", "PHL-LN-0003", ""))

    def test_c4_loan_already_closed(self):
        out = self.call(4, "ปิดสินเชื่อบ้าน", "ใช่", "ปิดเลย", "ปิดเอง", "ภายใน 7 วัน", "0045")
        self.assertEqual(out["action"], "continue")
        self.assertEqual(self.c.bot.sessions["genesys:payoff-c4"].history[-1][1],
                         "ขอบคุณครับคุณมานี สินเชื่อบ้าน ลงท้าย 0004 ปิดบัญชีไปแล้วครับ ให้เจ้าหน้าที่ช่วยตรวจสอบต่อไหมครับ")
        out = self.call(4, "ใช่")
        self.assertEqual((out["action"], out["handoffReason"], out["topic"], out["loan_number"]),
                         ("handoff", "loan_not_active", "payoff", "PHL-LN-0004"))

    def test_c5_high_ltv_loan_info(self):
        out = self.call(5, "ข้อมูลสินเชื่อ", "0053")
        self.assertIn("คงเหลือ 3,900,000 บาท",
                      self.c.bot.sessions["genesys:payoff-c5"].history[-1][1])      # as written; speech reads it

    def test_c6_rate_review(self):
        out = self.call(6, "ขอลดดอกเบี้ยบ้านครับ", "ใช่", "0061")
        self.assertEqual((out["action"], out["topic"], out["loan_number"]),
                         ("handoff", "homeloan_inquiry", "PHL-LN-0006"))

    def test_not_verified_gives_no_kyc(self):
        out = self.call(2, "ขอคุยกับเจ้าหน้าที่", "เจ้าหน้าที่")
        self.assertEqual((out["action"], out["verifiedPhone"], out["kyc_result"], out["identify_type"]),
                         ("handoff", "", "", ""))
