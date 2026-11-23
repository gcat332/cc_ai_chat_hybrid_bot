import sqlite3
import tempfile
import unittest
from pathlib import Path

from callcenter_bot import Bot, backend, db, tables
from callcenter_bot.thai_format import speech_text


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")
        self.bot = Bot()

    def say(self, *lines):
        return [self.bot.reply("s", line) for line in lines][-1]

    def test_seeded_demo_rows(self):
        tables = db.all_tables()
        self.assertEqual([len(tables[t]) for t in ("customers", "deposit_accounts", "credit_cards", "loans")],
                         [10, 5, 3, 10])
        ploysai = backend.find_customer("3294367792962")
        self.assertEqual((ploysai["title"], ploysai["first_name"], ploysai["last_name"], ploysai["phone"]),
                         ("นางสาว", "พลอยใส", "ใจดี", "0815493626"))
        self.assertEqual([c["number"] for c in tables[db.CASE_TABLE]], ["CS0001001"])
        self.assertEqual(len(tables["faq"]), 46)

    def test_bot_reads_what_the_admin_saved(self):
        tables.save("customers", {"national_id": "1-1017-00123-46-4", "title": "นาง", "first_name": "มานี",
                                  "phone": "091-234-5678"})
        tables.save("deposit_accounts", {"account_no": "9999999999", "national_id": "1101700123464",
                                         "account_type": "ออมทรัพย์", "balance": "2,000.25"})
        r = self.say("ยอดเงินในบัญชี", "1101700123464")
        self.assertIn("ลงท้าย 9999 คงเหลือ 2,000.25 บาท", r.text)

    def test_balance_change_shows_at_once(self):
        tables.save("credit_cards", {"outstanding": "0"}, "5412000011112222")
        self.assertIn("ไม่มียอดค้างชำระ", self.say("ยอดค้างชำระ", "1509900543215").text)

    def test_invalid_rows_are_refused_in_thai(self):
        bad = [
            ("customers", {"national_id": "1234567890123", "first_name": "x"}, "เลขบัตรประชาชน"),
            ("customers", {"national_id": "1101700123464", "first_name": ""}, "ชื่อ"),
            ("customers", {"national_id": "1101700123464", "first_name": "x", "phone": "12345"}, "เบอร์โทร"),
            ("deposit_accounts", {"account_no": "123", "national_id": "3294367792962", "account_type": "x"}, "10 หลัก"),
            ("deposit_accounts", {"account_no": "1111111111", "national_id": "1101700123464", "account_type": "x"},
             "ไม่มีลูกค้า"),
            ("credit_cards", {"card_no": "4532", "national_id": "3294367792962", "card_name": "x"}, "16 หลัก"),
            ("credit_cards", {"card_no": "4532000000000000", "national_id": "3294367792962", "card_name": "x",
                              "outstanding": "-5"}, "ติดลบ"),
            ("loans", {"loan_no": "X1", "national_id": "3294367792962", "loan_type": "x", "next_due_date": "5/12/69"},
             "วันที่"),
            ("faq", {"topic": "x", "title": "t", "keywords": "k", "answer": "a", "action": "offer_ticket"}, "handoff"),
        ]
        for table, row, words in bad:
            with self.subTest(table=table, row=row), self.assertRaises(tables.Refused) as e:
                tables.save(table, row)
            self.assertIn(words, str(e.exception))

    def test_shop_demo_database_becomes_the_bank_demo(self):
        """A database from the first (online shop) demo: dropped and loaded with the bank's rows;
        its tickets kept as cases."""
        path = Path(tempfile.mkdtemp()) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE customers (phone TEXT PRIMARY KEY, name TEXT, id_last4 TEXT, balance REAL, due_date TEXT);
            CREATE TABLE orders (order_id TEXT PRIMARY KEY, phone TEXT, status TEXT);
            CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, description TEXT NOT NULL,
                                  status TEXT NOT NULL DEFAULT 'รอดำเนินการ', created_at TEXT);
            INSERT INTO customers VALUES ('0812345678', 'สมชาย', '1234', 0, NULL);
            INSERT INTO tickets (description) VALUES ('เรื่องเก่า');""")
        conn.commit()
        conn.close()
        db.use_database(str(path))
        self.assertIsNotNone(backend.find_customer("3294367792962"))
        self.assertFalse(db.query("SELECT 1 FROM sqlite_master WHERE name IN ('orders', 'tickets')"))
        numbers = {c["number"]: c["short_description"] for c in db.all_tables()[db.CASE_TABLE]}
        self.assertEqual(numbers["CS0001001"], "เรื่องเก่า")          # the old ticket kept its number
        db.use_database(":memory:")

    def test_rows_saved_in_the_browser_come_back(self):
        saved = db.export_rows()
        tables.delete("loans", "HL6201234567")
        db.import_rows(saved)
        self.assertEqual(len(db.all_tables()["loans"]), 10)
        db.import_rows({"customers": [{"phone": "0812345678"}]})     # the shop demo's rows: ignored
        self.assertEqual(len(db.all_tables()["customers"]), 10)


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
        "สแกน 7-Eleven ที่ร้าน": "สแกน เซเว่นอีเลฟเว่น, ที่ร้าน",
        "บริษัท ตัวอย่าง จำกัด ยินดี": "บริษัท ตัวอย่าง จำกัด, ยินดี",
    }

    def test_cases(self):
        for text, spoken in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(speech_text(text, {"7-Eleven": "เซเว่นอีเลฟเว่น"},
                                             keep_together=("บริษัท ตัวอย่าง จำกัด",)), spoken)

    def test_every_reply_has_speech(self):
        db.use_database(":memory:")
        self.assertTrue(Bot().reply("s", "ยอดค้างชำระ").speech)


if __name__ == "__main__":
    unittest.main()
