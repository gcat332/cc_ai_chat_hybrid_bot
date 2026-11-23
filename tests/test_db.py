import unittest

from callcenter_bot import Bot, backend, db
from callcenter_bot.thai_format import speech_text


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")
        self.bot = Bot()

    def say(self, *lines):
        return [self.bot.reply("s", line) for line in lines][-1]

    def test_seeded_demo_rows(self):
        tables = db.all_tables()
        self.assertEqual(len(tables["customers"]), 4)
        self.assertEqual(len(tables["orders"]), 4)
        self.assertEqual(tables["tickets"], [])

    def test_test_number_0636538939(self):
        r = self.say("เช็คยอด", "063-653-8939", "8939")
        self.assertIn("คุณทดสอบ มียอดค้างชำระ 520.75 บาท ครบกำหนดชำระวันที่ 15 ธันวาคม 2569", r.text)

    def test_bot_reads_what_the_admin_saved(self):
        db.save_customer({"phone": "091-234-5678", "name": "มานี", "id_last4": "9999",
                          "balance": "2,000.25", "due_date": "2026-12-31"})
        r = self.say("เช็คยอด", "0912345678", "9999")
        self.assertIn("คุณมานี มียอดค้างชำระ 2,000.25 บาท ครบกำหนดชำระวันที่ 31 ธันวาคม 2569", r.text)

    def test_balance_change_shows_at_once(self):
        db.save_customer({"phone": "0812345678", "name": "สมชาย", "id_last4": "1234", "balance": 0})
        self.assertIn("ไม่มียอดค้างชำระ", self.say("เช็คยอด", "0812345678", "1234").text)

    def test_ticket_is_stored(self):
        r = self.say("อินเทอร์เน็ตใช้ไม่ได้ตั้งแต่เช้าครับ", "ใช่")
        ticket = db.all_tables()["tickets"][0]
        self.assertIn(ticket["ticket_no"], r.text)
        self.assertEqual(ticket["description"], "อินเทอร์เน็ตใช้ไม่ได้ตั้งแต่เช้า")
        self.assertEqual(ticket["status"], "รอดำเนินการ")

    def test_ticket_remembers_verified_phone(self):
        self.say("เช็คยอด", "0812345678", "1234", "แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่")
        self.assertEqual(db.all_tables()["tickets"][0]["phone"], "0812345678")

    def test_order_without_date_or_tracking(self):
        db.save_order({"order_id": "777777", "status": "รอชำระเงิน"})
        r = self.say("ติดตามพัสดุ", "777777")
        self.assertEqual(r.text, "คำสั่งซื้อเลข 777777 สถานะ: รอชำระเงิน ค่ะ")

    def test_rename_phone_keeps_orders(self):
        db.save_customer({"phone": "0899999999", "name": "สมชาย", "id_last4": "1234", "balance": 1},
                         old_phone="0812345678")
        self.assertEqual(db.query("SELECT phone FROM orders WHERE order_id='123456'")[0]["phone"], "0899999999")
        self.assertIsNone(backend.find_customer("0812345678"))

    def test_invalid_rows_are_refused_in_thai(self):
        bad = [
            (db.save_customer, {"phone": "12345", "name": "x", "id_last4": "1234"}, "เบอร์โทร"),
            (db.save_customer, {"phone": "0812345678", "name": "", "id_last4": "1234"}, "ชื่อ"),
            (db.save_customer, {"phone": "0812345678", "name": "x", "id_last4": "12"}, "4 ตัวท้าย"),
            (db.save_customer, {"phone": "0812345678", "name": "x", "id_last4": "1234", "balance": "-5"}, "ติดลบ"),
            (db.save_customer, {"phone": "0812345678", "name": "x", "id_last4": "1234", "due_date": "5/12/69"}, "วันที่"),
            (db.save_order, {"order_id": "12", "status": "x"}, "6 หลัก"),
            (db.save_order, {"order_id": "999999", "status": "x", "phone": "0800000000"}, "ไม่มีลูกค้า"),
        ]
        for save, row, words in bad:
            with self.subTest(row=row), self.assertRaises(db.InvalidRow) as e:
                save(row)
            self.assertIn(words, str(e.exception))


class SpeechTextTest(unittest.TestCase):
    """What text-to-speech reads must say the same thing as the text on screen."""
    CASES = {
        # numbers one digit at a time, in groups, like an agent reads them back
        "เช่น 0812345678": "เช่น ศูนย์ แปด หนึ่ง, สอง สาม สี่, ห้า หก เจ็ด แปด",
        "เลข 123456 ค่ะ": "เลข หนึ่ง สอง สาม, สี่ ห้า หก ค่ะ",
        "หมายเลข TK1001": "หมายเลข ที เค, หนึ่ง ศูนย์ ศูนย์ หนึ่ง",
        "โทร 02-123-4567": "โทร ศูนย์ สอง, หนึ่ง สอง สาม, สี่ ห้า หก เจ็ด",
        "ไม่พบหมายเลข 080-xxx-0000 ในระบบ": "ไม่พบหมายเลข, ที่ลงท้ายด้วย ศูนย์ ศูนย์ ศูนย์ ศูนย์, ในระบบ",
        "ยอด 1,250.50 บาท": "ยอด 1250 บาท 50 สตางค์",
        "ยอด 389.00 บาท": "ยอด 389 บาท",
        "08:00–20:00 น.": "8 นาฬิกา ถึง 20 นาฬิกา",
        "วันที่ 5 ธันวาคม 2569": "วันที่ 5 ธันวาคม 2569",       # dates and years read as numbers
        "เลข 4 ตัวท้าย 10 หลัก": "เลข 4 ตัวท้าย 10 หลัก",
        # pauses: "." after a sentence, "," between phrases, none inside names
        "สวัสดีค่ะ ยินดีต้อนรับ": "สวัสดีค่ะ. ยินดีต้อนรับ",
        "คุณสมชาย มียอดค้างชำระ": "คุณสมชาย, มียอดค้างชำระ",
        "ต่อไปนี้ค่ะ\n1. แอปธนาคาร\n2. 7-Eleven": "ต่อไปนี้ค่ะ. ข้อ 1 แอปธนาคาร. ข้อ 2 เซเว่นอีเลฟเว่น",
        "สแกน 7-Eleven ที่ร้าน": "สแกน เซเว่นอีเลฟเว่น ที่ร้าน",
        "บริษัท ตัวอย่าง จำกัด ยินดี": "บริษัท ตัวอย่าง จำกัด, ยินดี",
    }

    def test_cases(self):
        for text, spoken in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(speech_text(text, {"7-Eleven": "เซเว่นอีเลฟเว่น"},
                                             keep_together=("บริษัท ตัวอย่าง จำกัด",)), spoken)

    def test_every_reply_has_speech(self):
        db.use_database(":memory:")
        r = Bot().reply("s", "เช็คยอด 0812345678")
        self.assertTrue(r.speech)
        self.assertNotIn("0812345678", Bot().reply("t", "เช็คยอด").speech)


if __name__ == "__main__":
    unittest.main()
