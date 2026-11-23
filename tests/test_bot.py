import unittest
from datetime import datetime
from unittest import mock

from callcenter_bot import Bot, backend, config, db
from callcenter_bot.bot import THAI_TIME

# Agent hours are tested in test_bot.ProactiveTest; here a handoff must work at any time of day.
config.AGENT_HOURS = None
from callcenter_bot.intents import detect, is_cancel, yes_no
from callcenter_bot.normalize import compact, digits_only, normalize


class NormalizeTest(unittest.TestCase):
    def test_thai_digits_and_separators(self):
        self.assertEqual(digits_only("๐๘๑-๒๓๔ ๕๖๗๘"), "0812345678")

    def test_stretched_letters_but_not_digits(self):
        self.assertEqual(normalize("ครับบบบ"), "ครับ")
        self.assertEqual(normalize("0811112222"), "0811112222")

    def test_spoken_digits(self):
        self.assertEqual(digits_only("ศูนย์แปดหนึ่ง สองสามสี่ ห้าหกเจ็ดแปด"), "0812345678")
        self.assertEqual(digits_only("หนึ่งสองสามสี่"), "1234")
        self.assertEqual(digits_only("หกล้มสามคน"), "หกล้มสามคน")  # words, not a number

    def test_particles_and_spaces_removed(self):
        self.assertEqual(compact("ยกเลิก ครับ"), "ยกเลิก")
        self.assertEqual(compact("ไม่ใช่ค่ะ"), "ไม่ใช่")


class IntentTest(unittest.TestCase):
    CASES = {
        "สวัสดีค่ะ": "greeting",
        "บิลเดือนนี้ต้องจ่ายเท่าไหร่": "check_balance",
        "จ่ายได้ที่ไหนบ้าง": "payment_channels",
        "ของยังไม่มาเลย": "order_status",
        "เน็ตหลุดบ่อยมาก": "report_problem",
        "ขอคุยกับเจ้าหน้าที่หน่อย": "agent",
        "เปิดกี่โมง": "hours",
        "ขอบคุณมากครับ": "thanks",
        "บายบาย": "goodbye",
        "this is fine": None,  # "hi" inside "this" must not count as a greeting
    }

    def test_detect(self):
        for text, expected in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(detect(text)[0], expected)

    def test_cancel_only_on_its_own(self):
        self.assertTrue(is_cancel("ยกเลิกค่ะ"))
        self.assertFalse(is_cancel("ยกเลิกคำสั่งซื้อ"))

    def test_yes_no(self):
        self.assertIs(yes_no("ใช่ครับ"), True)
        self.assertIs(yes_no("ไม่ใช่ค่ะ"), False)
        self.assertIsNone(yes_no("ไม่แน่ใจ"))
        self.assertIs(yes_no("ใช่ครับ ถูกต้องครับ"), True)  # spoken answers run on
        self.assertIs(yes_no("ไม่ใช่ค่ะ ผิด"), False)
        self.assertIsNone(yes_no("nothing"))


class ConversationTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")  # fresh demo tables for every test, never the real file
        self.bot = Bot()

    def say(self, *lines, session="s"):
        return [self.bot.reply(session, line) for line in lines][-1]

    def test_balance_needs_verification(self):
        r = self.say("เช็คยอดค้างชำระ", "081-234-5678", "1234")
        self.assertIn("1,250.50 บาท", r.text)
        self.assertIn("ครบกำหนดวันที่ 5 ธันวาคม", r.text)
        # Verified once per session: asking again answers straight away.
        self.assertIn("1,250.50", self.say("ดูยอดอีกที").text)

    def test_expects_digits_while_waiting_for_a_number(self):
        self.assertEqual(self.say("เช็คยอดค้างชำระ").expects, "digits")
        self.assertEqual(self.say("0812345678").expects, "digits")  # now the ID digits
        self.assertIsNone(self.say("1234").expects)                  # answered: no keypad

    def test_phone_in_first_message(self):
        r = self.say("เช็คยอด 0812345678 ครับ")
        self.assertIn("4 ตัวท้าย", r.text)

    def test_wrong_id_three_times_hands_off(self):
        r = self.say("เช็คยอด", "0812345678", "0000", "1111", "2222")
        self.assertTrue(r.handoff)
        self.assertNotIn("1,250.50", r.text)

    def test_unknown_phone(self):
        r = self.say("เช็คยอด", "0800000000")
        self.assertIn("ไม่พบเบอร์ 080-xxx-0000", r.text)

    def test_balance_by_voice(self):
        r = self.say("อยากเช็คยอดค้างชำระ", "ศูนย์แปดหนึ่ง สองสามสี่ ห้าหกเจ็ดแปด", "หนึ่ง สอง สาม สี่")
        self.assertIn("1,250.50 บาท", r.text)

    def test_order_status(self):
        r = self.say("ติดตามพัสดุ", "123456")
        self.assertIn("Kerry Express", r.text)

    def test_problem_ticket(self):
        r = self.say("อินเทอร์เน็ตใช้ไม่ได้ตั้งแต่เช้าครับ", "ใช่", "0899999999")
        self.assertEqual(r.intent, "ticket_created")
        self.assertIn("CS0001001", r.text)

    def test_switch_topic_mid_flow(self):
        r = self.say("เช็คยอด", "ของยังไม่มาเลย")
        self.assertEqual(r.intent, "order_status")

    def test_cancel_mid_flow(self):
        r = self.say("เช็คยอด", "ยกเลิกครับ")
        self.assertEqual(r.intent, "cancel")

    def test_agent_any_time(self):
        r = self.say("เช็คยอด", "ขอคุยกับพนักงาน")
        self.assertTrue(r.handoff)

    def test_offers_agent_after_misunderstanding(self):
        r = self.say("asdf", "qwerty")
        self.assertIn("คุยกับเจ้าหน้าที่", r.quick_replies)

    def test_goodbye_ends_session(self):
        self.say("เช็คยอด", "0812345678", "1234", session="x")
        r = self.say("จบการสนทนา", session="x")
        self.assertTrue(r.end)
        self.assertNotIn("x", self.bot.sessions)

    def test_fallback_hook(self):
        bot = Bot(fallback=lambda message, session: "คำตอบจาก FAQ")
        self.assertEqual(bot.reply("s", "สมัครสมาชิกยังไง").text, "คำตอบจาก FAQ")


MONDAY_10AM = datetime(2026, 11, 23, 10, 0, tzinfo=THAI_TIME)
MONDAY_10PM = datetime(2026, 11, 23, 22, 0, tzinfo=THAI_TIME)


class FollowUpTest(unittest.TestCase):
    """Questions customers ask next, in a fixed week (Monday 23 November 2026, 10:00)."""

    def setUp(self):
        db.use_database(":memory:")
        self.bot = Bot(clock=lambda: MONDAY_10AM)
        self.saved_hours, config.AGENT_HOURS = config.AGENT_HOURS, {d: (8, 20) for d in range(7)}

    def tearDown(self):
        config.AGENT_HOURS = self.saved_hours

    def say(self, *lines, session="s"):
        return [self.bot.reply(session, line) for line in lines][-1]

    # ---- billing ----
    def test_balance_offers_payment_channels_aloud(self):
        r = self.say("เช็คยอดค้างชำระ", "0636538939", "8939")
        self.assertIn("ต้องการทราบช่องทางชำระเงินไหม", r.text)   # asked aloud: works on the phone
        self.assertIn("พร้อมเพย์", self.say("ใช่ค่ะ").text)

    def test_other_question_after_the_offer(self):
        self.say("เช็คยอดค้างชำระ", "0636538939", "8939")
        self.assertEqual(self.say("ขอใบเสร็จ").intent, "receipt")    # not stuck on "ใช่ หรือไม่ใช่"

    def test_overdue_balance_says_so(self):
        db.save_customer({"phone": "0812345678", "name": "สมชาย", "id_last4": "1234",
                          "balance": 100, "due_date": "2026-11-01"})
        self.assertIn("เลยกำหนดแล้ว", self.say("เช็คยอด", "0812345678", "1234").text)

    def test_faq_from_the_table(self):
        self.assertEqual(self.say("จ่ายช้ามีค่าปรับไหม").intent, "late_fee")
        r = self.say("ขอผ่อนจ่ายได้ไหม", session="b")
        self.assertEqual((r.intent, r.handoff), ("payment_arrangement", True))
        db.execute("UPDATE faq SET answer = 'คำตอบใหม่ค่ะ' WHERE topic = 'late_fee'")   # edited on the data page
        self.assertEqual(self.say("ค่าปรับเท่าไหร่", session="c").text, "คำตอบใหม่ค่ะ")

    def test_paid_but_not_updated_opens_ticket_with_verified_phone(self):
        self.say("เช็คยอด", "0636538939", "8939")
        r = self.say("จ่ายแล้วแต่ยอดยังไม่ลด", "ใช่")
        self.assertEqual(r.intent, "ticket_created")               # verified: no callback question
        t = db.all_tables()[db.CASE_TABLE][0]
        self.assertEqual((t["consumer"], t["category"], t["contact_type"]), ("0636538939", "payment_not_updated", "web"))

    # ---- orders: the bot never changes an order itself ----
    def test_cancel_before_shipping_sends_a_request(self):
        r = self.say("ยกเลิกออเดอร์ 111222")
        self.assertIn("ส่งคำขอยกเลิก", r.text)
        r = self.say("ใช่", "0899999999")
        self.assertEqual(r.intent, "ticket_created")
        t = db.all_tables()[db.CASE_TABLE][0]
        self.assertEqual((t["category"], t["order_id"], t["callback_phone"]), ("order_cancel", "111222", "0899999999"))

    def test_cancel_after_shipping_explains_returns(self):
        r = self.say("ยกเลิกคำสั่งซื้อ", "123456")
        self.assertIn("ยกเลิกไม่ได้แล้ว", r.text)
        self.assertIn("ขอคืนสินค้า", r.quick_replies)

    def test_change_address_goes_to_an_agent_with_the_order(self):
        r = self.say("ขอเปลี่ยนที่อยู่จัดส่ง 123456")
        self.assertEqual((r.handoff, r.intent, r.context["order"]), (True, "order_change_address", "123456"))

    def test_late_order_offers_a_ticket(self):
        r = self.say("ติดตามพัสดุ 777888")                          # expected 20 November
        self.assertIn("เลยวันที่คาดว่าจะได้รับแล้ว", r.text)
        self.assertEqual(self.say("ใช่", "0899999999").intent, "ticket_created")
        self.assertEqual(db.all_tables()[db.CASE_TABLE][0]["category"], "order_late")

    def test_on_time_order_offers_nothing(self):
        self.assertNotIn("เลยวันที่", self.say("ติดตามพัสดุ 636538").text)

    def test_delivered_but_not_received(self):
        r = self.say("ขึ้นว่าส่งแล้วแต่ยังไม่ได้ของ", "654321")
        self.assertIn("จัดส่งสำเร็จเมื่อวันที่ 18 พฤศจิกายน", r.text)
        self.assertEqual(r.intent, "order_not_received")

    def test_wrong_item_return(self):
        r = self.say("ได้ของผิดค่ะ", "654321")
        self.assertIn("คืนหรือเปลี่ยนสินค้า", r.text)
        self.say("ใช่", "0899999999")
        case = db.all_tables()[db.CASE_TABLE][0]
        self.assertEqual(case["short_description"], "ขอคืน/เปลี่ยนสินค้า คำสั่งซื้อ 654321")
        self.assertIn("ได้ของผิด", case["description"])                  # the customer's own words

    # ---- tickets ----
    def test_ticket_status_by_number(self):
        self.say("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")
        # As typed, as Genesys hears it, the short form, and the old TK numbers.
        for line in ("เรื่อง CS0001001 ถึงไหนแล้ว", "ซีเอส 0001001", "เช็คเรื่อง cs1001", "เรื่อง TK1001"):
            r = self.say(line, session=line)
            self.assertIn("เรื่อง CS0001001", r.text)
            self.assertIn("สถานะ รับเรื่องแล้ว", r.text)
            self.assertNotIn("เน็ตหลุด", r.text)                   # no details without verification
        self.assertIn("ขอเลขที่เรื่อง", self.say("เช็คเรื่อง", session="x").text)
        self.assertIn("CS0001001", self.say("1001", session="x").text)
        self.assertIn("ไม่พบเรื่องเลขที่ CS0001999", self.say("เช็คเรื่อง CS0001999", session="y").text)

    def test_case_states_from_servicenow_values(self):
        self.say("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")
        db.execute(f"UPDATE {db.CASE_TABLE} SET state = 6")              # Resolved
        r = self.say("เช็คเรื่อง CS0001001", session="r")
        self.assertIn("สถานะ แก้ไขแล้ว", r.text)
        self.assertNotIn("เร่งเรื่อง", r.text)                         # finished: nothing to speed up
        db.execute(f"UPDATE {db.CASE_TABLE} SET state = 18")             # Awaiting Info: offer the agent
        r = self.say("เช็คเรื่อง CS0001001", session="a")
        self.assertIn("รอข้อมูลเพิ่มเติมจากลูกค้า", r.text)
        r = self.say("ใช่", session="a")
        self.assertEqual((r.handoff, r.context["ticket"]), (True, "CS0001001"))

    def test_case_system_down_hands_over(self):
        def down(*args, **kwargs):
            raise backend.CaseError("ServiceNow not reachable")
        with mock.patch.object(backend, "create_case", down), mock.patch.object(backend, "get_case", down):
            r = self.say("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")
            self.assertEqual((r.handoff, r.intent), (True, "case_error"))
            r = self.say("เช็คเรื่อง CS0001001", session="g")
            self.assertEqual((r.handoff, r.intent), (True, "case_error"))
            night = Bot(clock=lambda: MONDAY_10PM)     # even at night: no call-back offer that would fail again
            r = [night.reply("n", line) for line in ("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")][-1]
            self.assertTrue(r.handoff)

    def test_phone_channel_recorded(self):
        [self.bot.reply("genesys:c1", line) for line in ("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")]
        self.assertEqual(db.all_tables()[db.CASE_TABLE][0]["contact_type"], "phone")

    def test_ticket_created_says_how_to_follow_up(self):
        self.assertIn("เช็คเรื่อง CS0001001", self.say("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999").text)

    # ---- never stuck ----
    def test_other_request_while_describing_a_problem(self):
        self.assertEqual(self.say("แจ้งปัญหา", "ขอใบเสร็จ").intent, "receipt")

    def test_forgot_id_during_verification(self):
        r = self.say("เช็คยอด", "0636538939", "ลืมเลขบัตร")
        self.assertEqual((r.handoff, r.intent), (True, "forgot_id"))

    # ---- agents and hours ----
    def test_handoff_carries_order_and_ticket(self):
        r = self.say("ติดตามพัสดุ 636538", "ขอคุยกับเจ้าหน้าที่")
        self.assertEqual(r.context, {"order": "636538"})

    def test_out_of_hours_offers_a_call_back(self):
        bot = Bot(clock=lambda: MONDAY_10PM)
        r = bot.reply("n", "ขอคุยกับเจ้าหน้าที่")
        self.assertFalse(r.handoff)
        self.assertIn("นอกเวลาทำการ", r.text)
        r = [bot.reply("n", line) for line in ("ใช่", "0899999999")][-1]
        self.assertEqual(r.intent, "ticket_created")
        self.assertEqual(db.all_tables()[db.CASE_TABLE][0]["category"], "callback")
        self.assertIn("นอกเวลาทำการ", bot.reply("h", "เปิดกี่โมง").text)

    def test_no_hours_check_when_agents_always_answer(self):
        config.AGENT_HOURS = None
        self.assertTrue(Bot(clock=lambda: MONDAY_10PM).reply("n", "ขอคุยกับเจ้าหน้าที่").handoff)


if __name__ == "__main__":
    unittest.main()
