import unittest
from datetime import datetime, timedelta
from unittest import mock

from callcenter_bot import Bot, backend, config, db
from callcenter_bot.bot import THAI_TIME
from callcenter_bot.intents import detect, is_cancel, yes_no
from callcenter_bot.normalize import compact, digits_only, normalize
from callcenter_bot.tables import valid_national_id

MONDAY_10AM = datetime(2026, 11, 23, 10, 0, tzinfo=THAI_TIME)
MONDAY_10PM = datetime(2026, 11, 23, 22, 0, tzinfo=THAI_TIME)
PLOYSAI = "3294367792962"      # นางสาวพลอยใส ใจดี: home loan, Platinum card, savings, case CS0001001
SOMCHAI = "1101700123456"      # นายสมชาย ใจงาม: personal and home loans, Signature card
VIPHA = "3100500678905"        # นางวิภา รักษ์ดี: home loan, savings, no credit card
TEST = "1509900543215"         # นายทดสอบ ระบบ (phone 0636538939): Classic card 520.75 due
NOT_CUSTOMERS = ("1509900543223", "3100500678913", "1101700123464")   # valid numbers, nobody's


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

    def test_national_id_checksum(self):
        self.assertTrue(valid_national_id(PLOYSAI))
        self.assertFalse(valid_national_id("3294367792961"))
        self.assertFalse(valid_national_id("12345"))


class IntentTest(unittest.TestCase):
    CASES = {
        "สวัสดีค่ะ": "greeting",
        "ยอดค้างชำระบัตรเครดิตเดือนนี้": "balance_due",
        "ยอดชำระขั้นต่ำเท่าไหร่": "balance_due",
        "สอบถามสินเชื่อบ้าน": "loan_info",
        "ต้องการปิดบัญชีสินเชื่อบ้านค่ะ": "loan_close",
        "อยากรีไฟแนนซ์บ้าน": "loan_close",
        "วงเงินบัตรเครดิตเหลือเท่าไหร่": "card_info",
        "สมัครบัตรเครดิต": "card_apply",
        "ขอเพิ่มวงเงินบัตรเครดิต": "card_limit",
        "ยกเลิกบัตรเครดิต": "card_cancel",
        "ยอดเงินในบัญชีเหลือเท่าไหร่": "deposit_balance",
        "โอนเงินไม่ได้": "transaction_help",
        "บัตรเครดิตหาย": "card_lost",
        "มีรายการที่ไม่ได้ทำในบัตร": "unauthorized",
        "อยากร้องเรียนการให้บริการ": "complaint",
        "เรื่องร้องเรียนถึงไหนแล้ว": "case_status",
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
        self.assertFalse(is_cancel("ยกเลิกบัตรเครดิต"))

    def test_yes_no(self):
        self.assertIs(yes_no("ใช่ครับ"), True)
        self.assertIs(yes_no("ไม่ใช่ค่ะ"), False)
        self.assertIsNone(yes_no("ไม่แน่ใจ"))


class BotTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")  # fresh demo tables for every test, never the real file
        self.bot = Bot(clock=lambda: MONDAY_10AM)
        self.saved_hours, config.AGENT_HOURS = config.AGENT_HOURS, None

    def tearDown(self):
        config.AGENT_HOURS = self.saved_hours

    def say(self, *lines, session="s"):
        return [self.bot.reply(session, line) for line in lines][-1]


class GreetingTest(BotTest):
    def test_welcome_reads_the_five_services(self):
        r = self.bot.welcome()
        self.assertEqual(r.text, "สวัสดีครับ ผู้ช่วยอัตโนมัติ ต้องการติดต่อเรื่องใดครับ")
        self.assertEqual(r.quick_replies, config.MAIN_MENU)        # the services as buttons
        self.assertNotIn("ยอดค้างชำระ", self.say("อะไรนะ").text)      # lost: asked again openly, no topics named
        self.assertEqual(r.quick_replies, config.MAIN_MENU)

    def test_menu_buttons_narrow_the_question(self):
        r = self.say("สินเชื่อและรีไฟแนนซ์")
        self.assertIn("ปิดบัญชีสินเชื่อ", r.quick_replies)
        self.assertFalse(r.handoff)
        self.assertIn("เลขบัตรประชาชน", self.say("ยอดค้างชำระ", session="b").text)   # straight to the inquiry


class SampleCallTest(BotTest):
    """The bank's sample script."""

    def test_close_home_loan_details_first(self):
        r = self.say("ต้องการปิดบัญชีสินเชื่อบ้านค่ะ")
        self.assertEqual(r.text, "ต้องการปิดบัญชีสินเชื่อบ้าน ใช่ไหมครับ")
        r = self.say("ใช่ค่ะ")
        self.assertEqual(r.text, "ต้องการปิดบัญชีเลย หรือสอบถามรายละเอียดก่อนครับ")
        r = self.say("ต้องการทราบรายละเอียดก่อนค่ะ ว่าต้องดำเนินการอย่างไรบ้าง")
        self.assertEqual(r.text, "ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเองครับ")
        r = self.say("จะรีไฟแนนซ์ไปกสิกรค่ะ")
        self.assertEqual(r.text, "ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่ครับ")
        r = self.say("สามจุดสองห้าเปอร์เซ็นต์ คงที่สองปี มีเงินคืนห้าพันบาทค่ะ")
        self.assertEqual(r.text, "รับทราบครับ ต้องการปิดบัญชีภายในกี่วันครับ")
        r = self.say("ภายในเดือนหน้าค่ะ")
        self.assertEqual(r.text, "เข้าใจครับ ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")
        self.assertEqual(r.expects, "digits")
        r = self.say(PLOYSAI)
        self.assertEqual(r.text, "ขอบคุณครับคุณพลอยใส ผมจะโอนให้เจ้าหน้าที่ตรวจสอบสินเชื่อ และแนะนำทางเลือกที่เหมาะสมครับ "
                                 "กรุณารอสักครู่ครับ")
        self.assertTrue(r.handoff)
        self.assertEqual(r.intent, "loan_refinance")
        self.assertEqual(r.context, {
            "request": "ปิดบัญชีสินเชื่อบ้านเพื่อรีไฟแนนซ์ (สอบถามรายละเอียดก่อน)",
            "reason": "รีไฟแนนซ์ไปธนาคารอื่น (กสิกรไทย)",
            "reason_code": "refinance",
            "offer": {"new_bank_name": "กสิกรไทย", "new_interest_rate": "3.25", "cashback_offered": "5000",
                      "promotion_period_months": "24", "closing_within_days": "30"},
            "loan": "สินเชื่อบ้าน ลงท้าย 4567 คงเหลือ 2,350,000 บาท ดอกเบี้ย 5.25% ค่างวด 18,500 บาท เหลือ 214 งวด",
            "loan_no": "HL6201234567",
            "customerName": "นางสาวพลอยใส ใจดี"})

    def test_refinance_proceed(self):
        self.say("จะรีไฟแนนซ์บ้านไปธนาคารอื่น", "ใช่")
        r = self.say("ดำเนินการเลย", "ยังไม่ทราบ", "ไม่รีบ", PLOYSAI)
        self.assertEqual((r.intent, r.context["request"]),
                         ("loan_refinance", "ปิดบัญชีสินเชื่อบ้านเพื่อรีไฟแนนซ์ (ต้องการดำเนินการปิดบัญชี)"))

    def test_wrong_guess_is_corrected(self):
        r = self.say("ปิดบัญชีสินเชื่อ", "ไม่ใช่")
        self.assertIn("ต้องการติดต่อเรื่องใด", r.text)
        self.assertFalse(r.handoff)


class InquiryTest(BotTest):
    """The bot answers these itself, but only to a verified customer."""

    def test_balance_due_after_verification(self):
        r = self.say("ยอดค้างชำระบัตรเครดิตเท่าไหร่")
        self.assertNotIn("37,550", r.text)                         # nothing before verification
        r = self.say(PLOYSAI)
        self.assertIn("บัตร Platinum ลงท้าย 7788 ยอดค้าง 37,550 บาท ขั้นต่ำ 3,755 บาท", r.text)
        self.assertIn("ครบกำหนด 10 ธันวาคม", r.text)
        self.assertNotIn("สินเชื่อบ้าน", r.text)                    # asked about the card only
        self.assertIn("แอปธนาคาร", self.say("ใช่").text)   # payment channels, offered aloud

    def test_balance_due_lists_cards_and_loans(self):
        r = self.say("ยอดที่ต้องชำระเดือนนี้", PLOYSAI)
        self.assertIn("Platinum", r.text)
        self.assertIn("สินเชื่อบ้าน ค่างวด 18,500 บาท ครบกำหนด 5 ธันวาคม", r.text)

    def test_verified_once_per_conversation(self):
        self.say("ยอดเงินในบัญชี", PLOYSAI)
        r = self.say("สินเชื่อบ้านเหลือเท่าไหร่")                   # no second identity check
        self.assertIn("คงเหลือ 2,350,000 บาท ดอกเบี้ย 5.25 เปอร์เซ็นต์", r.text)
        self.assertIn("เหลือ 214 งวด", r.text)

    def test_deposit_and_card(self):
        self.assertIn("ลงท้าย 7890 คงเหลือ 85,420.50 บาท", self.say("ยอดเงินในบัญชี", PLOYSAI).text)
        self.assertIn("วงเงินคงเหลือ 112,450 บาท จาก 150,000 บาท", self.say("วงเงินบัตรเครดิต").text)

    def test_numbers_are_spoken_well(self):
        r = self.say("ยอดเงินในบัญชี", PLOYSAI)
        self.assertIn("ลงท้าย เจ็ด แปด เก้า ศูนย์", r.speech)       # last digits one by one
        self.assertIn("85420 บาท 50 สตางค์", r.speech)              # money as an amount

    def test_overdue_is_said(self):
        db.execute("UPDATE credit_cards SET due_date = '2026-11-01' WHERE national_id = ?", (TEST,))
        self.assertIn("เลยกำหนดแล้ว", self.say("ยอดค้างชำระ", TEST).text)

    def test_customer_without_a_card(self):
        self.assertIn("ไม่พบบัตรเครดิต", self.say("วงเงินบัตรเครดิตเหลือเท่าไหร่", VIPHA).text)

    def test_spoken_id_number(self):
        r = self.say("ยอดค้างชำระ", "หนึ่ง ห้า ศูนย์ เก้า เก้า ศูนย์ ศูนย์ ห้า สี่ สาม สอง หนึ่ง ห้า")
        self.assertIn("520.75", r.text)


class RequestTest(BotTest):
    """Requests that open work: confirm, verify, hand over. The bot never opens cases itself."""

    def test_requests_go_to_an_agent_with_the_request(self):
        for line, reason, detail in (("สมัครบัตรเครดิต", "card_apply", "สมัครบัตรเครดิต"),
                                     ("ขอเพิ่มวงเงินบัตรเครดิต", "card_limit", "เพิ่มวงเงินบัตรเครดิต"),
                                     ("ยกเลิกบัตรเครดิต", "card_cancel", "ยกเลิกบัตรเครดิต"),
                                     ("ร้องเรียนการให้บริการ", "complaint", "แจ้งปัญหาการใช้งานหรือร้องเรียนการให้บริการ")):
            with self.subTest(line=line):
                r = self.say(line, session=line)
                self.assertIn("ใช่ไหมครับ", r.text)
                self.say("ใช่", session=line)
                r = self.say(PLOYSAI, session=line)
                self.assertEqual((r.handoff, r.intent, r.context["request"]), (True, reason, detail))
        self.assertEqual(db.query(f"SELECT COUNT(*) AS n FROM {db.CASE_TABLE}")[0]["n"], 1)   # still the seeded one

    def test_urgent_needs_no_confirmation(self):
        r = self.say("บัตรเครดิตหาย")
        self.assertIn("เลขบัตรประชาชน", r.text)                    # straight to verification
        r = self.say(PLOYSAI)
        self.assertEqual((r.handoff, r.intent), (True, "card_lost"))
        self.assertIn("ระงับบัตรโดยด่วน", r.text)

    def test_faq_answer_and_faq_handoff(self):
        r = self.say("ปิดก่อนกำหนดมีค่าปรับไหม")
        self.assertEqual((r.intent, r.handoff), ("prepayment_fee", False))
        r = self.say("ขอเปลี่ยนเบอร์โทร", session="b")
        self.assertIn("เลขบัตรประชาชน", r.text)                    # verify, then the agent
        r = self.say(PLOYSAI, session="b")
        self.assertEqual((r.handoff, r.intent), (True, "update_contact"))

    def test_agent_asks_to_verify_first_but_can_skip(self):
        r = self.say("ขอคุยกับเจ้าหน้าที่")
        self.assertIn("ยืนยันตัวตน", r.text)
        self.assertFalse(r.handoff)
        r = self.say("ขอคุยกับเจ้าหน้าที่")                         # again: no more questions
        self.assertTrue(r.handoff)
        self.assertNotIn("customerName", r.context)

    def test_switch_topic_while_verifying(self):
        self.say("ยอดค้างชำระ")
        self.assertEqual(self.say("เปิดกี่โมง").intent, "hours")

    def test_cancel_mid_flow(self):
        self.assertEqual(self.say("ยอดค้างชำระ", "ยกเลิกครับ").intent, "cancel")

    def test_offers_agent_after_misunderstanding(self):
        r = self.say("asdf", "qwerty")
        self.assertEqual(r.text, "ขอโทษอีกครั้งครับ ให้ผมต่อสายเจ้าหน้าที่ช่วยดูแลไหมครับ")
        self.assertEqual(self.say("ใช่ครับ").text,          # a spoken yes works: verify, then hand over
                         "ก่อนโอนสาย ไม่สะดวกให้เลขบัตร พูดว่า เจ้าหน้าที่ อีกครั้งได้ครับ "
                         "ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")

    def test_goodbye_ends_session(self):
        self.say("ยอดเงินในบัญชี", PLOYSAI, session="x")
        r = self.say("จบการสนทนา", session="x")
        self.assertTrue(r.end)
        self.assertNotIn("x", self.bot.sessions)

    def test_fallback_hook(self):
        bot = Bot(fallback=lambda message, session: "คำตอบจาก FAQ")
        self.assertEqual(bot.reply("s", "สมัครสมาชิกยังไง").text, "คำตอบจาก FAQ")

    def test_out_of_hours(self):
        config.AGENT_HOURS = {d: (8, 20) for d in range(7)}
        night = Bot(clock=lambda: MONDAY_10PM)
        r = [night.reply("n", line) for line in ("ยกเลิกบัตรเครดิต", "ใช่", PLOYSAI)][-1]
        self.assertFalse(r.handoff)
        self.assertIn("นอกเวลาทำการ", r.text)


class IdentityTest(BotTest):
    def test_wrong_id_gives_one_answer_and_hands_over_after_three(self):
        r = self.say("ยอดค้างชำระ", NOT_CUSTOMERS[0])
        self.assertIn("ข้อมูลไม่ตรงกับในระบบ", r.text)
        self.say(NOT_CUSTOMERS[1])
        r = self.say(NOT_CUSTOMERS[2])
        self.assertEqual((r.handoff, r.intent), (True, "verify_failed"))
        self.assertNotIn("520", r.text)

    def test_mistyped_id_is_not_a_failure(self):
        r = self.say("ยอดค้างชำระ", "3294367792961")                # checksum wrong
        self.assertIn("เลขบัตรไม่ถูกต้อง", r.text)
        self.assertEqual(db.query("SELECT COUNT(*) AS n FROM verify_failures")[0]["n"], 0)
        self.assertIn("37,550", self.say(PLOYSAI).text)

    def test_lockout_per_id_across_calls(self):
        for call in ("c1", "c2", "c3"):
            self.say("ยอดค้างชำระ", NOT_CUSTOMERS[0], session=call)
        r = self.say("ยอดค้างชำระ", NOT_CUSTOMERS[0], session="c4")
        self.assertEqual((r.handoff, r.intent), (True, "verify_locked"))
        later = Bot(clock=lambda: MONDAY_10AM + timedelta(minutes=config.VERIFY_LOCK_MINUTES + 1))
        r = [later.reply("c5", line) for line in ("ยอดค้างชำระ", NOT_CUSTOMERS[0])][-1]
        self.assertIn("ข้อมูลไม่ตรงกับในระบบ", r.text)              # checked again after the lock

    def test_success_clears_failures(self):
        db.execute("INSERT INTO verify_failures (identity, failed_at) VALUES (?, '2026-11-23 09:59:00')", (PLOYSAI,))
        self.say("ยอดค้างชำระ", PLOYSAI)
        self.assertEqual(db.query("SELECT COUNT(*) AS n FROM verify_failures")[0]["n"], 0)

    def test_forgot_id_goes_to_an_agent(self):
        r = self.say("ยอดค้างชำระ", "ลืมเลขบัตร")
        self.assertIn("ไม่เป็นไรครับ", r.text)
        r = self.say("ขอคุยกับเจ้าหน้าที่")                          # one step to the agent
        self.assertTrue(r.handoff)


class CallerNumberTest(BotTest):
    """Calling from the registered phone (Genesys ANI): the last 4 ID digits are enough."""

    def call(self, ani="tel:+66815493626", session="call"):
        self.bot.set_caller(session, ani)
        return session

    def test_four_digits_from_the_registered_phone(self):
        sid = self.call()
        r = self.say("ยอดเงินในบัญชี", session=sid)
        self.assertEqual(r.text, "ขอเลขบัตรประชาชน 4 ตัวท้าย เพื่อยืนยันตัวตนครับ")
        r = self.say("2962", session=sid)
        self.assertTrue(r.text.startswith("ขอบคุณครับคุณพลอยใส "))
        self.assertIn("85,420.50", r.text)
        self.assertEqual(self.bot.sessions[sid].verified_by, "เบอร์ที่โทรเข้า + เลขบัตร 4 ตัวท้าย")

    def test_spoken_and_full_number_also_work(self):
        self.assertIn("85,420.50", self.say("ยอดเงินในบัญชี", "สอง เก้า หก สอง", session=self.call(session="a")).text)
        self.assertIn("85,420.50", self.say("ยอดเงินในบัญชี", PLOYSAI, session=self.call(session="b")).text)

    def test_wrong_digits(self):
        sid = self.call()
        r = self.say("ยอดเงินในบัญชี", "1111", session=sid)
        self.assertIn("ขอเลขบัตร 4 ตัวท้ายอีกครั้ง", r.text)
        self.say("2222", session=sid)
        r = self.say("3333", session=sid)
        self.assertEqual((r.handoff, r.intent), (True, "verify_failed"))
        r = self.say("ยอดเงินในบัญชี", "2962", session=self.call(session="again"))
        self.assertEqual(r.intent, "verify_locked")                 # 3 failures on this customer

    def test_other_numbers_need_the_full_id(self):
        for ani in ("tel:+66899999999", "", "anonymous"):
            with self.subTest(ani=ani):
                sid = self.call(ani, session=ani or "none")
                self.assertIn("13 หลัก", self.say("ยอดค้างชำระ", session=sid).text)

    def test_number_formats(self):
        from callcenter_bot.normalize import phone_from_ani
        for ani in ("tel:+66815493626", "+66 81 549 3626", "0815493626", "sip:0815493626@pbx"):
            self.assertEqual(phone_from_ani(ani), "0815493626")
        self.assertEqual(phone_from_ani("anonymous"), "")


class TranscriptTest(BotTest):
    def test_summary_and_transcript(self):
        from callcenter_bot import transcripts
        self.say("ยอดเงินในบัญชี", PLOYSAI, "ขอเพิ่มวงเงินบัตรเครดิต", "ใช่")
        s = self.bot.sessions["s"]
        self.assertEqual(transcripts.summary(s, "เพิ่มวงเงินบัตรเครดิต"),
                         "ยืนยันตัวตนแล้ว (เลขบัตรประชาชน 13 หลัก) | ต้องการ: เพิ่มวงเงินบัตรเครดิต | ถามเรื่อง: ยอดเงินในบัญชี")
        text = transcripts.transcript(s)
        self.assertTrue(text.startswith("ลูกค้า: ยอดเงินในบัญชี\nบอท: ขอเลขบัตรประชาชน 13 หลัก"))
        self.assertNotIn(PLOYSAI, text)                             # masked
        self.assertEqual(len(transcripts.fit("ก" * 900)), 500)
        self.assertTrue(transcripts.fit("ก" * 900).startswith("…"))



class CaseTest(BotTest):
    def test_own_case_status(self):
        r = self.say("เรื่อง CS0001001 ถึงไหนแล้ว", PLOYSAI)
        self.assertIn("เรื่อง CS0001001 กำลังดำเนินการ", r.text)
        r = self.say("ขอคุยกับเจ้าหน้าที่")
        self.assertEqual(r.context["case"], "CS0001001")

    def test_number_forms(self):
        for line in ("ซีเอส 0001001", "เช็คเรื่อง cs1001", "เรื่อง TK1001"):
            with self.subTest(line=line):
                self.assertIn("เรื่อง CS0001001", self.say(line, PLOYSAI, session=line).text)
        self.assertIn("CS0001001", self.say("เช็คเรื่อง", PLOYSAI, "1001", session="n").text)

    def test_someone_elses_case_is_not_shown(self):
        r = self.say("เรื่อง CS0001001 ถึงไหนแล้ว", SOMCHAI)
        self.assertIn("ไม่พบเรื่อง CS0001001 ของคุณลูกค้า", r.text)
        self.assertNotIn("ดำเนินการ", r.text)
        self.assertNotIn("case", self.say("ขอคุยกับเจ้าหน้าที่").context)

    def test_states_and_close_notes(self):
        db.execute(f"UPDATE {db.CASE_TABLE} SET state = 6, close_notes = 'คืนค่าธรรมเนียมแล้ว'")
        r = self.say("เช็คเรื่อง CS0001001", PLOYSAI)
        self.assertIn("CS0001001 แก้ไขแล้วครับ คืนค่าธรรมเนียมแล้ว", r.text)   # with the agent's notes
        db.execute(f"UPDATE {db.CASE_TABLE} SET state = 18")
        r = self.say("เช็คเรื่อง CS0001001", PLOYSAI, session="a")
        self.assertIn("รอข้อมูลเพิ่มเติมจากคุณลูกค้า", r.text)
        r = self.say("ใช่", session="a")
        self.assertEqual((r.handoff, r.context["case"]), (True, "CS0001001"))

    def test_guessing_is_stopped(self):
        self.say("เช็คเรื่อง CS0002001", PLOYSAI, session="g")
        self.say("2002", session="g")
        r = self.say("2003", session="g")
        self.assertEqual((r.handoff, r.intent), (True, "case_not_found"))

    def test_case_without_owner_goes_to_an_agent(self):
        backend.create_case("เปิดโดยเจ้าหน้าที่", "manual")         # CS0001002, nobody's
        r = self.say("เช็คเรื่อง CS0001002", PLOYSAI)
        self.assertEqual((r.handoff, r.intent), (True, "case_check"))

    def test_case_system_down(self):
        def down(*args, **kwargs):
            raise backend.CaseError("ServiceNow not reachable")
        with mock.patch.object(backend, "get_case", down):
            r = self.say("เช็คเรื่อง CS0001001", PLOYSAI)
        self.assertEqual((r.handoff, r.intent), (True, "case_error"))

    def test_phone_channel(self):
        self.bot.reply("genesys:c1", "สวัสดี")
        self.assertEqual(self.bot.sessions["genesys:c1"].channel, "phone")


if __name__ == "__main__":
    unittest.main()


class ConversationTest(BotTest):
    """Talking like a person: fillers, short answers to menus, "anything else?", names."""

    def test_filler_is_not_a_miss(self):
        self.assertEqual(self.say("เอ่อ").text, "ครับ บอกเรื่องที่ต้องการได้เลยครับ")
        self.assertEqual(self.say("อ๋อ ครับ").text, "ต้องการติดต่อเรื่องอะไร เล่าสั้นๆ ได้เลยครับ")
        self.assertEqual(self.bot.sessions["s"].misunderstood, 0)
        self.assertEqual(self.say("ฮัลโหล").text, "ได้ยินครับ ต้องการติดต่อเรื่องใดครับ")

    def test_not_understood_asks_the_greeting_question_again(self):
        self.assertEqual(self.say("ทาง ค่าใช้จ่าย").text,
                         "ขอโทษครับ ผมยังไม่เข้าใจ รบกวนพูดอีกครั้งสั้นๆ ได้ไหมครับ")

    def test_short_answer_to_a_menu(self):
        self.say("บัญชีเงินฝาก")
        r = self.say("สอบถาม")
        self.assertEqual(r.text, "ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")
        self.assertEqual(r.intent, "deposit_balance")
        self.say("บัตรเครดิต", session="c")
        self.assertEqual(self.say("เพิ่ม", session="c").intent, "card_limit")

    def test_not_understood_in_a_menu_asks_the_menu_again(self):
        self.say("บัญชีเงินฝาก")
        self.assertEqual(self.say("ทุกวัน").text, "ขอโทษครับ สอบถามยอดเงินในบัญชี หรือธุรกรรมโอน ฝาก ถอนครับ")
        self.assertEqual(self.say("ยอดครับ").intent, "deposit_balance")

    def test_bare_amount_asks_which(self):
        self.assertEqual(self.say("เช็คยอด").text, "ยอดค้างชำระ หรือยอดเงินในบัญชีครับ")
        self.assertEqual(self.say("ค้างชำระ").intent, "balance_due")

    def test_vague_question_asks_what(self):
        r = self.say("ขอสอบถามหน่อยครับ")
        self.assertEqual(r.text, "ได้ครับ สอบถามเรื่องใดครับ")
        self.assertEqual(self.bot.sessions["s"].misunderstood, 0)

    def test_anything_else_then_no_ends_with_the_name(self):
        r = self.say("ยอดเงินในบัญชี", PLOYSAI)
        self.assertTrue(r.text.startswith("ขอบคุณครับคุณพลอยใส "))
        self.assertTrue(r.text.endswith("มีอะไรให้ช่วยเพิ่มเติมไหมครับ"))
        r = self.say("ไม่มีครับ")
        self.assertEqual(r.text, "ขอบคุณคุณพลอยใสที่ใช้บริการครับ สวัสดีครับ")
        self.assertTrue(r.end)

    def test_anything_else_then_yes_or_a_new_question(self):
        self.say("เปิดกี่โมง")
        self.assertEqual(self.say("มีครับ").text, "ได้ครับ บอกเรื่องที่ต้องการได้เลยครับ")
        self.say("เปิดกี่โมง")
        self.assertEqual(self.say("บัตรหายครับ").intent, "card_lost")

    def test_polite_particle_answers_yes(self):
        self.say("สมัครบัตรเครดิต")
        self.assertEqual(self.say("ครับ").text, "ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")

    def test_filler_while_waiting_for_a_number(self):
        self.say("ยอดค้างชำระ")
        r = self.say("เอ่อ")
        self.assertEqual(r.text, "ไม่ต้องรีบครับ ขอเลขบัตรประชาชน 13 หลักครับ")
        self.assertEqual(self.bot.sessions["s"].retries, 0)

    def test_asked_again_in_other_words(self):
        self.say("ยอดค้างชำระ")
        self.assertEqual(self.say("ไม่รู้สิ").text, "ขอโทษครับ ขอเลขบัตรประชาชน 13 หลักครับ")
        self.assertEqual(self.say("ไม่รู้สิ").text, "รบกวนพูดเลขบัตรประชาชนทีละตัว ให้ครบ 13 หลักครับ")
        r = self.say("ไม่รู้สิ")
        self.assertEqual(r.text, "ขอโทษครับ ให้ผมต่อสายเจ้าหน้าที่ช่วยดูแลไหมครับ")
        self.assertTrue(self.say("ใช่").handoff)

    def test_registered_phone_retry_prompt(self):
        self.bot.set_caller("call", "tel:+66815493626")
        self.say("ยอดเงินในบัญชี", session="call")
        self.assertEqual(self.say("ไม่แน่ใจ", session="call").text, "ขอโทษครับ ขอเลขบัตรประชาชน 4 ตัวท้ายครับ")

    def test_clipped_word_is_asked_again(self):
        r = self.say("ครับ ลูก")
        self.assertEqual(r.text, "ขอโทษครับ ได้ยินไม่ครบ รบกวนพูดอีกครั้งครับ")
        self.assertEqual(self.bot.sessions["s"].misunderstood, 0)
        self.assertEqual(self.say("ก็ ค้างชำระ").intent, "balance_due")    # a clipped start still works

    def test_first_line_of_a_call_misheard_is_not_a_miss(self):
        sid = "genesys-first"
        self.assertEqual(self.say("อ้าว ทุกวัน", session=sid).text,
                         "ขอโทษครับ เมื่อกี้ได้ยินไม่ชัด รบกวนพูดอีกครั้งได้ไหมครับ")
        self.assertEqual(self.bot.sessions[sid].misunderstood, 0)
        self.assertEqual(self.say("ทาง ค่าใช้จ่าย", session=sid).text,
                         "ขอโทษครับ ผมยังไม่เข้าใจ รบกวนพูดอีกครั้งสั้นๆ ได้ไหมครับ")

    def test_yes_is_not_a_fragment(self):
        self.say("สมัครบัตรเครดิต")
        self.assertEqual(self.say("ครับ ใช่").text, "ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")




class LoanCloseScenarioTest(BotTest):
    """Other ways the loan-closing call goes: reasons said early, hesitation, several loans,
    someone else's account, side questions."""

    def handed(self, *lines):
        r = self.say(*lines)
        self.assertTrue(r.handoff, r.text)
        return r

    def test_everything_said_at_once(self):
        r = self.say("อยากปิดสินเชื่อบ้าน จะย้ายไปไทยพาณิชย์ ขอรายละเอียดก่อน")
        self.assertEqual(r.text, "ต้องการปิดบัญชีสินเชื่อบ้าน ใช่ไหมครับ")
        self.assertEqual(self.say("ใช่").text, "ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่ครับ")
        self.assertEqual(self.say("ยังไม่ทราบค่ะ").text, "ต้องการปิดบัญชีภายในกี่วันครับ")
        self.assertEqual(self.say("ยังไม่กำหนด").text, "เข้าใจครับ ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ")
        r = self.handed(PLOYSAI)
        self.assertEqual(r.context["reason"], "รีไฟแนนซ์ไปธนาคารอื่น (ไทยพาณิชย์)")

    def test_details_instead_of_yes(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน")
        self.assertEqual(self.say("อยากรู้รายละเอียดก่อนค่ะ").text, "ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเองครับ")

    def test_reason_instead_of_mode(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่")
        self.assertEqual(self.say("จะเอาเงินก้อนมาโปะค่ะ").text,
                         "รับทราบครับ ต้องการปิดบัญชีเลย หรือสอบถามรายละเอียดก่อนครับ")
        self.assertEqual(self.say("ปิดเลย").text, "ต้องการปิดบัญชีภายในกี่วันครับ")
        self.assertIn("เลขบัตรประชาชน", self.say("อาทิตย์หน้า").text)

    def test_reason_not_given_never_blocks(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่", "ปิดเลย")
        self.assertEqual(self.say("อืม แล้วแต่").text, "ขอโทษครับ ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเองครับ")
        self.assertEqual(self.say("เรื่องครอบครัว").text, "ต้องการปิดบัญชีภายในกี่วันครับ")
        self.assertIn("เลขบัตรประชาชน", self.say("ไม่รีบครับ").text)
        r = self.handed(PLOYSAI)
        self.assertEqual(r.context["reason"], "อื่นๆ: เรื่องครอบครัว")

    def test_declines_to_say_why(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่", "ปิดเลย")
        self.assertEqual(self.say("ไม่สะดวกบอกค่ะ").text, "ต้องการปิดบัญชีภายในกี่วันครับ")
        self.assertIn("เลขบัตรประชาชน", self.say("สิ้นเดือน").text)
        self.assertEqual(self.handed(PLOYSAI).context["reason"], "ไม่ระบุ")

    def test_sell_the_house(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่", "ปิดเลย")
        self.say("ขายบ้านแล้วค่ะ", "ภายใน 10 วัน")
        r = self.handed(PLOYSAI)
        self.assertEqual((r.intent, r.context["reason"]), ("loan_close", "ขายหลักทรัพย์"))

    def test_hesitates_then_rate_review(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่")
        self.assertEqual(self.say("ขอคิดดูก่อนค่ะ").text, "ได้ครับ ระหว่างนี้ให้เจ้าหน้าที่ช่วยดูข้อเสนอดอกเบี้ยให้ไหมครับ")
        self.assertIn("เลขบัตรประชาชน", self.say("ได้ค่ะ").text)
        r = self.handed(PLOYSAI)
        self.assertEqual(r.intent, "loan_rate_review")
        self.assertIn("ลงท้าย 4567", r.context["loan"])

    def test_hesitates_and_declines(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่", "ขอคิดดูก่อน")
        self.assertEqual(self.say("ไม่ต้องครับ").text, "ได้ครับ มีอะไรให้ช่วยเพิ่มเติมไหมครับ")

    def test_side_question_keeps_the_step(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน", "ใช่")
        r = self.say("ปิดก่อนกำหนดมีค่าปรับไหม")
        self.assertTrue(r.text.startswith("สินเชื่อบ้านที่ปิดบัญชีภายใน 3 ปีแรก"))
        self.assertTrue(r.text.endswith("ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเองครับ"))

    def test_two_loans_asks_which(self):
        self.say("ปิดสินเชื่อ", "ใช่", "ปิดเลย", "ปิดเอง", "ภายใน 30 วัน")
        r = self.say(SOMCHAI)
        self.assertEqual(r.text, "ขอบคุณครับคุณสมชาย เป็นบัญชีสินเชื่อบ้าน ลงท้าย 8899 หรือสินเชื่อส่วนบุคคล "
                                 "ลงท้าย 6543ครับ")
        r = self.handed("ส่วนบุคคลครับ")
        self.assertTrue(r.context["loan"].startswith("สินเชื่อส่วนบุคคล ลงท้าย 6543 คงเหลือ 85,000 บาท"))

    def test_two_loans_by_last_digits(self):
        self.say("ปิดสินเชื่อ", "ใช่", "ปิดเลย", "ปิดเอง", "ภายใน 30 วัน", SOMCHAI)
        self.assertTrue(self.handed("ลงท้าย 8899").context["loan"].startswith("สินเชื่อบ้าน ลงท้าย 8899"))

    def test_two_loans_type_said_first(self):
        self.say("ปิดสินเชื่อบ้าน", "ใช่", "ปิดเลย", "ปิดเอง", "ภายใน 30 วัน")
        r = self.handed(SOMCHAI)
        self.assertTrue(r.context["loan"].startswith("สินเชื่อบ้าน ลงท้าย 8899 คงเหลือ 1,680,000 บาท"))

    def test_no_loan_still_goes_to_an_agent(self):
        db.execute("DELETE FROM loans WHERE national_id = ?", (PLOYSAI,))
        self.say("ปิดสินเชื่อ", "ใช่", "ปิดเลย", "ปิดเอง", "ภายใน 30 วัน")
        r = self.handed(PLOYSAI)
        self.assertIn("ไม่พบบัญชีสินเชื่อ", r.text)
        self.assertEqual(r.context["loan"], "ไม่พบบัญชีสินเชื่อในระบบ")

    def test_someone_elses_loan(self):
        r = self.handed("อยากปิดสินเชื่อบ้านของแม่ค่ะ")
        self.assertEqual(r.text, "เรื่องบัญชีของผู้อื่น ต้องให้เจ้าหน้าที่ตรวจสอบสิทธิ์ก่อนครับ กรุณารอสักครู่ครับ")
        self.assertEqual((r.intent, r.context["request"]), ("third_party", "ปิดบัญชีสินเชื่อ (โทรแทนเจ้าของบัญชี)"))

    def test_borrower_passed_away(self):
        r = self.handed("ผู้กู้เสียชีวิตแล้วค่ะ จะปิดสินเชื่อ")
        self.assertTrue(r.text.startswith("ขอแสดงความเสียใจด้วยครับ"))
        self.assertEqual(r.intent, "deceased")

    def test_bare_close_account_asks_which(self):
        self.assertEqual(self.say("อยากปิดบัญชี").text, "ปิดบัญชีสินเชื่อ หรือบัญชีเงินฝากครับ")
        self.assertEqual(self.say("เงินฝาก").text, "ต้องการปิดบัญชีเงินฝาก ใช่ไหมครับ")

    def test_rate_review_and_restructure(self):
        self.assertEqual(self.say("ขอลดดอกเบี้ยบ้านได้ไหม").text, "ต้องการขอพิจารณาอัตราดอกเบี้ยสินเชื่อ ใช่ไหมครับ")
        r = self.handed("ใช่", PLOYSAI)
        self.assertEqual(r.intent, "loan_rate_review")
        self.assertIn("ลงท้าย 4567", r.context["loan"])
        self.bot.reset("s")
        self.assertEqual(self.say("ผ่อนไม่ไหวแล้วค่ะ").intent, "loan_restructure")

    def test_no_but_something_else(self):
        self.say("ปิดบัญชีสินเชื่อบ้าน")
        self.assertEqual(self.say("ไม่ใช่ค่ะ อยากเช็คยอดค้างชำระ").intent, "balance_due")


class FaqTest(BotTest):
    """Every example FAQ is reached by its own words, and not taken by a built-in topic."""

    def test_every_faq_keyword_reaches_its_entry(self):
        for entry in backend.faq_entries():
            for keyword in entry["keywords"]:
                with self.subTest(topic=entry["topic"], keyword=keyword):
                    said = f" {keyword} " if keyword.isascii() else keyword     # English is typed with spaces
                    intent, faq = self.bot._detect(f"อยากสอบถามเรื่อง{said}หน่อยครับ")
                    self.assertEqual((intent, faq and faq["topic"]), ("faq", entry["topic"]))

    def test_questions_as_people_ask_them(self):
        asked = {
            "ค่าธรรมเนียมรายปีบัตรเครดิตเท่าไหร่ครับ": "card_annual_fee",
            "สมัครบัตรต้องใช้เอกสารอะไรบ้าง": "card_requirements",
            "อยากเปิดบัญชีเงินฝากค่ะ": "account_open",
            "โอนไปต่างประเทศยังไง": "fx_rate",
            "ขอหนังสือรับรองดอกเบี้ยไว้ลดหย่อนภาษี": "tax_certificate",
            "ตู้ไม่จ่ายเงินแต่ตัดเงินในบัญชีไปแล้ว": "atm_no_cash",
            "otp ไม่มาครับ": "otp_not_received",
            "มีคนโทรมาอ้างว่าเป็นธนาคาร": "phishing",
            "เบอร์คอลเซ็นเตอร์อะไรนะ": "hotline",
            "ปิดสินเชื่อแล้วจะได้โฉนดคืนเมื่อไหร่": "mortgage_release",
        }
        for message, topic in asked.items():
            with self.subTest(message=message):
                self.assertEqual(self.say(message, session=message).intent, topic)

    def test_open_is_not_close(self):
        self.assertNotEqual(self.say("เปิดบัญชีเงินฝาก").intent, "deposit_close")
        self.assertEqual(self.say("ปิดบัญชีเงินฝาก", session="c").intent, "deposit_close")

    def test_answers_end_with_anything_else(self):
        r = self.say("ค่าโอนต่างธนาคารเสียไหม")
        self.assertEqual(r.text, "โอนผ่านแอปไม่มีค่าธรรมเนียม ทั้งในและต่างธนาคารครับ มีอะไรให้ช่วยเพิ่มเติมไหมครับ")


class SecondPhoneTest(BotTest):
    """นางสาวพลอยใส calls from 0815493626 (main) or 0875679673 (customer_phones)."""

    def test_both_numbers_need_only_four_digits(self):
        for n, ani in enumerate(("tel:+66815493626", "tel:+66875679673")):
            sid = f"genesys-{n}"
            self.bot.set_caller(sid, ani)
            self.assertEqual(self.say("ยอดเงินในบัญชี", session=sid).text,
                             "ขอเลขบัตรประชาชน 4 ตัวท้าย เพื่อยืนยันตัวตนครับ")
            self.assertTrue(self.say("2962", session=sid).text.startswith("ขอบคุณครับคุณพลอยใส "))
            self.assertEqual(self.bot.sessions[sid].verified_phone, ani[-9:].rjust(10, "0"))

    def test_someone_elses_number_is_refused_as_second_phone(self):
        from callcenter_bot import tables
        with self.assertRaises(tables.Refused):
            tables.save("customer_phones", {"phone": "0812345678", "national_id": PLOYSAI})
        tables.save("customer_phones", {"phone": "0899999999", "national_id": PLOYSAI, "note": "ที่ทำงาน"})
        self.assertEqual(backend.customer_by_phone("0899999999")["first_name"], "พลอยใส")
