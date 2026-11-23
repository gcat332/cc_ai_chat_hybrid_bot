"""Mock-data page (python -m dataadmin): every table editable, the bot sees changes at once."""
import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from callcenter_bot import Bot, config, db
from dataadmin import server, store

config.AGENT_HOURS = None   # hours are tested in test_bot.FollowUpTest


class StoreTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")

    def table(self, name):
        return next(t for t in store.snapshot() if t["name"] == name)

    def test_all_tables_with_columns(self):
        names = [t["name"] for t in store.snapshot()]
        self.assertEqual(names[:4], ["customers", "orders", "sn_customerservice_case", "faq"])
        cols = [c["name"] for c in self.table("sn_customerservice_case")["columns"]]
        for name in ("sys_id", "number", "short_description", "state", "contact_type", "consumer"):
            self.assertIn(name, cols)
        self.assertEqual(self.table("sn_customerservice_case")["key"], "sys_id")
        self.assertEqual(self.table("faq")["key"], "topic")

    def test_customer_checks_are_kept(self):
        with self.assertRaises(store.Refused):
            store.save("customers", {"phone": "123", "name": "x", "id_last4": "1234"})
        store.save("customers", {"phone": "0911111111", "name": "มานี", "id_last4": "1111", "balance": "50"})
        bot = Bot()
        self.assertIn("4 ตัวท้าย", bot.reply("s", "เช็คยอด 0911111111").text)   # found: asks for the ID
        self.assertIn("คุณมานี มียอดค้างชำระ 50.00 บาท", bot.reply("s", "1111").text)

    def test_faq_add_edit_delete_reaches_the_bot(self):
        store.save("faq", {"topic": "wifi_password", "title": "รหัส wifi", "keywords": "รหัสไวไฟ,รหัสwifi",
                           "answer": "รหัสอยู่ใต้เราเตอร์ค่ะ", "action": "answer"})
        self.assertEqual(Bot().reply("s", "ลืมรหัสไวไฟ").text, "รหัสอยู่ใต้เราเตอร์ค่ะ")
        store.save("faq", {"answer": "ดูรหัสที่ฉลากใต้เราเตอร์ค่ะ"}, "wifi_password")
        self.assertEqual(Bot().reply("s2", "ลืมรหัสไวไฟ").text, "ดูรหัสที่ฉลากใต้เราเตอร์ค่ะ")
        store.delete("faq", "wifi_password")
        self.assertNotEqual(Bot().reply("s3", "ลืมรหัสไวไฟ").intent, "wifi_password")

    def test_faq_checks(self):
        for bad in ({"topic": "Late Fee", "title": "t", "keywords": "k", "answer": "a"},
                    {"topic": "ok", "title": "t", "keywords": "", "answer": "a"},
                    {"topic": "ok", "title": "t", "keywords": "k", "answer": "a", "action": "dance"}):
            with self.subTest(row=bad), self.assertRaises(store.Refused):
                store.save("faq", bad)

    def test_ticket_status_edit_shows_to_customers(self):
        bot = Bot()
        [bot.reply("s", line) for line in ("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")]
        case = self.table("sn_customerservice_case")["rows"][0]
        store.save("sn_customerservice_case", {"state": "6", "close_notes": "เปลี่ยนเราเตอร์แล้ว"}, case["sys_id"])
        self.assertIn("สถานะ แก้ไขแล้ว", Bot().reply("t", "เช็คเรื่อง CS0001001").text)

    def test_add_ticket_by_hand_and_refusals(self):
        number = store.save("sn_customerservice_case", {"short_description": "ทดสอบ", "category": "callback"})
        row = self.table("sn_customerservice_case")["rows"][0]
        self.assertEqual((number, row["number"], row["state"]), ("CS0001001", "CS0001001", 1))   # numbered, New
        self.assertRegex(row["sys_id"], r"^[0-9a-f]{32}$")
        with self.assertRaises(store.Refused):
            store.save("sn_customerservice_case", {"short_description": ""})
        with self.assertRaises(store.Refused):
            store.save("sn_customerservice_case", {"short_description": "x", "state": "ไม่ใช่ตัวเลข"})
        with self.assertRaises(store.Refused):
            store.save("customers", {"phone": "0812345678", "name": "x", "id_last4": "1"})
        with self.assertRaises(store.Refused):
            store.save("nope", {})

    def test_reset_brings_back_the_demo(self):
        store.delete("orders", "123456")
        store.save("faq", {"answer": "แก้แล้ว"}, "late_fee")
        store.reset()
        self.assertEqual(len(self.table("orders")["rows"]), 5)
        faq = {r["topic"]: r for r in self.table("faq")["rows"]}
        self.assertNotEqual(faq["late_fee"]["answer"], "แก้แล้ว")
        bot = Bot()
        [bot.reply("s", line) for line in ("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่")]
        self.assertIn("CS0001001", bot.reply("s", "0899999999").text)   # numbering starts again


class PageTest(unittest.TestCase):
    """The real HTTP server, as the browser calls it."""

    def start(self, password=""):
        db.use_database(":memory:")
        server.Handler.password = password
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.Handler.password = ""

    def call(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data, {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, json.loads(raw) if r.headers.get_content_type() == "application/json" else raw
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_page_and_api(self):
        self.start()
        status, page = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn("ข้อมูลจำลองของบอท".encode(), page)
        status, data = self.call("/api/tables")
        self.assertEqual([t["name"] for t in data["tables"]][:4], ["customers", "orders", "sn_customerservice_case", "faq"])
        status, out = self.call("/api/save", {"table": "orders", "row": {"order_id": "12", "status": "x"}})
        self.assertEqual(status, 400)
        status, out = self.call("/api/save", {"table": "orders", "row": {
            "order_id": "999999", "phone": "", "status": "กำลังเตรียมสินค้า", "eta": "2026-12-01"}})
        self.assertEqual((status, out["key"]), (200, "999999"))
        self.assertEqual(self.call("/api/delete", {"table": "orders", "key": "999999"})[0], 200)
        self.assertEqual(self.call("/api/reset", {})[0], 200)

    def test_password_when_set(self):
        self.start(password="s3cret")
        self.assertEqual(self.call("/api/tables")[0], 401)
        auth = {"Authorization": "Basic " + base64.b64encode(b"admin:s3cret").decode()}
        self.assertEqual(self.call("/api/tables", headers=auth)[0], 200)


if __name__ == "__main__":
    unittest.main()
