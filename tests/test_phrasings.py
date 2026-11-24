"""Topics reached by the many ways real callers say things: casual typing, and speech-to-text
lines with spaces between words or a misheard word ("ยอด คลัง" for "ยอดค้าง").

Add a line here whenever the log shows a caller the bot did not understand.
"""
import unittest

from callcenter_bot import Bot, db
from callcenter_bot.normalize import compact

# expected topic (built-in intent, or "faq:<topic>"; "a|b" = either) | what the caller said
PHRASINGS = """
faq:hotline | ถ้าต้องการติดต่อธนาคารต้องติดต่อไปที่เบอร์อะไร
faq:hotline | ช่องทางติดต่อธนาคาร
faq:hotline | ติดต่อธนาคารยังไง
faq:hotline | ต้นทางติดต่อธนาคาร
faq:hotline | ขอเบอร์โทรหน่อย
faq:hotline | เบอร์ call center
faq:hotline | คอลเซ็นเตอร์เบอร์อะไร
faq:hotline | มีเบอร์ให้โทรกลับไหม
faq:hotline | ติด ต่อ ธนาคาร ได้ ทาง ไหน
faq:hotline | ติดต่อแบงค์ยังไง
balance_due | ยอดค้างชำระ
balance_due | ยอด คลัง ชำระ
balance_due | ยอด คลัง ค่าใช้จ่าย
balance_due | เดือนนี้ต้องจ่ายเท่าไหร่
balance_due | ต้องโอนเท่าไร
balance_due | บิลเดือนนี้เท่าไหร่
balance_due | ยอดบิลบัตร
balance_due | ค้าง จ่าย เท่า ไหร่
balance_due | ครบกำหนดจ่ายวันไหน
balance_due | ต้องจ่ายวันไหน
balance_due | งวดนี้เท่าไหร่
balance_due | ค่าบ้านเดือนนี้เท่าไหร่
balance_due | ยอดที่ต้องจ่าย
balance_due | เช็คยอดหนี้บัตร
loan_info | ดอกเบี้ยบ้านตอนนี้กี่เปอร์เซ็นต์
loan_info | เหลือหนี้บ้านอีกเท่าไหร่
loan_info | ผ่อนบ้านเหลืออีกกี่งวด
loan_info | กู้บ้านไว้เหลือเท่าไร
loan_info | เงินต้นคงเหลือ
loan_info | หนี้ บ้าน เหลือ เท่า ไหร่
card_info | วงเงินบัตรเหลือเท่าไหร่
card_info | บัตรเครดิตใช้ได้อีกเท่าไหร่
card_info | เครดิตเหลือเท่าไหร่
card_info | วงเงินเหลือเท่าไร
deposit_balance | เงินในบัญชีเหลือเท่าไหร่
deposit_balance | ยอดเงินออมทรัพย์
deposit_balance | ในบัญชีมีเงินเท่าไหร่
deposit_balance | เงิน เหลือ เท่า ไหร่ ใน บัญชี
case_status | เรื่องที่แจ้งไว้ถึงไหนแล้ว
case_status | ติดตามเคส
case_status | เช็คสถานะเคส
case_status | แจ้งไปแล้วยังไม่มีใครติดต่อกลับ
payment_channels | จ่ายบัตรเครดิตช่องทางไหนได้บ้าง
payment_channels | ชำระค่างวดได้ที่ไหน
payment_channels | จ่ายผ่านเซเว่นได้ไหม
payment_channels | จ่ายบิลยังไง
payment_channels | ชำระ ผ่าน แอป ได้ ไหม
loan_close | อยากปิดบ้าน
loan_close | จะปิดหนี้บ้าน
loan_close | รีไฟ แนนซ์ บ้าน
loan_close | อยากย้ายไปธนาคารอื่น
loan_close | ยอดปิดบ้านเท่าไหร่
loan_close | ขายบ้านแล้วจะปิดหนี้
loan_close | ติดต่อธนาคารเรื่องปิดสินเชื่อบ้าน
loan_rate_review|loan_close | ขอลดดอกเบี้ยบ้านได้ไหม
loan_rate_review | ธนาคารอื่นให้ดอกถูกกว่า
loan_restructure | ผ่อนไม่ไหวแล้ว
loan_restructure | ตกงานจ่ายไม่ไหว
loan_restructure | จ่ายไม่ทัน ขอเลื่อนได้ไหม
deposit_close | อยากปิดบัญชีออมทรัพย์
deposit_close | ปิดบัญชีธนาคาร
card_apply | อยากทำบัตรเครดิต
card_limit | ขอขยายวงเงินชั่วคราว
card_cancel | ไม่อยากใช้บัตรแล้ว
transaction_help | โอนผิดคน
transaction_help | โอนไปแล้วปลายทางไม่ได้รับ
complaint | แอปเด้งออก
complaint | ระบบล่ม
card_lost | กระเป๋าตังค์หาย บัตรอยู่ในนั้น
card_lost | โดนขโมยกระเป๋า
unauthorized | โดนแฮก
unauthorized | มีคนเอาบัตรไปใช้
unauthorized | โดนตัดเงินไม่รู้ตัว
unauthorized | แก๊งคอลเซ็นเตอร์หลอกโอนเงิน
agent | ขอคุยกับคนจริง
agent | คุยกับบอทไม่รู้เรื่อง
hours|faq:hotline | คอลเซ็นเตอร์เปิดกี่โมง
hours | โทรได้ถึงกี่โมง
faq:late_fee | จ่ายช้าโดนค่าปรับเท่าไหร่
faq:payment_not_updated | โอนไปแล้วแต่ยังขึ้นค้างอยู่
faq:app_password | ลืมรหัสเข้าแอป
faq:app_locked | แอปโดนล็อก
faq:otp_not_received | otp ไม่เข้า
faq:otp_not_received | ไม่ได้ รับ โอ ที พี
faq:otp_not_received | sms ไม่เข้า
faq:phishing | มีคนโทรมาบอกว่าเป็นธนาคาร
faq:card_activate | บัตรใหม่เปิดใช้ยังไง
faq:card_declined | รูดบัตรไม่ผ่าน
faq:card_declined | บัตรใช้ไม่ได้
faq:card_delivery | บัตรยังไม่ได้รับเลย
faq:card_benefits | แลกแต้มยังไง
faq:card_cycle | บัตรตัดรอบวันไหน
faq:account_frozen | บัญชีถูกระงับ
faq:account_frozen | บัญชีถูกระงับครับ
faq:atm_no_cash | กดเงินแต่เงินไม่ออก
faq:statement | ขอสเตทเม้น
faq:forgot_id | จำเลขบัตรประชาชนไม่ได้
faq:promotion | มีโปรอะไรบ้าง
greeting | ฮัลโหล
greeting | ฮัลโหล ได้ยินไหม
"""


class PhrasingTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")
        self.bot = Bot()

    def test_real_phrasings_reach_their_topic(self):
        for line in PHRASINGS.strip().splitlines():
            expected, message = (part.strip() for part in line.rsplit("|", 1))
            with self.subTest(message=message):
                intent, faq = self.bot._detect(message)
                got = f"faq:{faq['topic']}" if intent == "faq" else intent
                self.assertIn(got, expected.split("|"))


class ParticleTest(unittest.TestCase):
    def test_words_ending_like_a_particle_are_kept(self):
        self.assertEqual(compact("บัญชีถูกระงับ"), "บัญชีถูกระงับ")       # ระงับ, not ระ + งับ
        self.assertEqual(compact("บัญชีถูกระงับครับ"), "บัญชีถูกระงับ")
        self.assertEqual(compact("โดนบังคับ"), "โดนบังคับ")                 # บังคับ, not บัง + คับ
        self.assertEqual(compact("ได้แล้วงับ"), "ได้แล้ว")
        self.assertEqual(compact("โอเคคับ"), "โอเค")


if __name__ == "__main__":
    unittest.main()
