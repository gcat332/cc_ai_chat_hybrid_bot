import unittest

from callcenter_bot import Bot, db
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
        r = self.say("อินเทอร์เน็ตใช้ไม่ได้ตั้งแต่เช้าครับ", "ใช่")
        self.assertEqual(r.intent, "ticket_created")
        self.assertIn("TK", r.text)

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


if __name__ == "__main__":
    unittest.main()
