"""Mock-data page (python -m dataadmin): every table editable, the bot sees changes at once."""
import base64
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from callcenter_bot import Bot, config, db
from callcenter_bot.bot import MORE
from dataadmin import server, store

config.AGENT_HOURS = None   # hours are tested in test_bot.RequestTest
PLOYSAI = "3294367792962"


class StoreTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")

    def table(self, name):
        return next(t for t in store.snapshot() if t["name"] == name)

    def test_all_tables_with_columns(self):
        names = [t["name"] for t in store.snapshot()]
        self.assertEqual(names, ["customers", "customer_phones", "deposit_accounts", "credit_cards", "loans",
                                 "sn_customerservice_case", "faq", "verify_failures"])
        cols = [c["name"] for c in self.table("sn_customerservice_case")["columns"]]
        for name in ("sys_id", "number", "short_description", "state", "contact_type", "consumer"):
            self.assertIn(name, cols)
        self.assertEqual((self.table("faq")["key"], self.table("customers")["key"]), ("topic", "national_id"))

    def test_new_customer_and_card_reach_the_bot(self):
        with self.assertRaises(store.Refused):
            store.save("customers", {"national_id": "1101700123465", "first_name": "x"})   # bad checksum
        store.save("customers", {"national_id": "1101700123464", "first_name": "มานี", "phone": "0911111111"})
        store.save("credit_cards", {"card_no": "4000123412341234", "national_id": "1101700123464",
                                    "card_name": "Classic", "credit_limit": "20000", "available_credit": "20000"})
        bot = Bot()
        r = [bot.reply("s", line) for line in ("วงเงินบัตรเครดิตเหลือเท่าไหร่", "1101700123464")][-1]
        self.assertIn("ลงท้าย 1234 วงเงินคงเหลือ 20,000 บาท", r.text)

    def test_faq_add_edit_delete_reaches_the_bot(self):
        store.save("faq", {"topic": "atm_limit", "title": "วงเงินถอน ATM", "keywords": "วงเงินatm,ถอนatm",
                           "answer": "ถอนเงินผ่าน ATM ได้วันละ 1 แสนบาทครับ", "action": "answer"})
        self.assertEqual(Bot().reply("s", "วงเงินATMต่อวัน").text, "ถอนเงินผ่าน ATM ได้วันละ 1 แสนบาทครับ " + MORE)
        store.save("faq", {"answer": "ถอนได้วันละ 2 แสนบาทครับ"}, "atm_limit")
        self.assertEqual(Bot().reply("s2", "วงเงินATMต่อวัน").text, "ถอนได้วันละ 2 แสนบาทครับ " + MORE)
        store.delete("faq", "atm_limit")
        self.assertNotEqual(Bot().reply("s3", "วงเงินATMต่อวัน").intent, "atm_limit")

    def test_faq_checks(self):
        for bad in ({"topic": "Late Fee", "title": "t", "keywords": "k", "answer": "a"},
                    {"topic": "ok", "title": "t", "keywords": "", "answer": "a"},
                    {"topic": "ok", "title": "t", "keywords": "k", "answer": "a", "action": "offer_ticket"}):
            with self.subTest(row=bad), self.assertRaises(store.Refused):
                store.save("faq", bad)

    def test_case_state_edit_shows_to_the_customer(self):
        case = self.table("sn_customerservice_case")["rows"][0]
        store.save("sn_customerservice_case", {"state": "6", "close_notes": "คืนค่าธรรมเนียมแล้ว"}, case["sys_id"])
        bot = Bot()
        r = [bot.reply("t", line) for line in ("เช็คเรื่อง CS0001001", PLOYSAI)][-1]
        self.assertIn("CS0001001 แก้ไขแล้ว", r.text)

    def test_add_case_by_hand_and_refusals(self):
        number = store.save("sn_customerservice_case", {"short_description": "ทดสอบ", "consumer": PLOYSAI})
        row = next(r for r in self.table("sn_customerservice_case")["rows"] if r["number"] == number)
        self.assertEqual((number, row["state"]), ("CS0001002", 1))            # numbered, New
        self.assertRegex(row["sys_id"], r"^[0-9a-f]{32}$")
        with self.assertRaises(store.Refused):
            store.save("sn_customerservice_case", {"short_description": ""})
        with self.assertRaises(store.Refused):
            store.save("sn_customerservice_case", {"short_description": "x", "state": "ไม่ใช่ตัวเลข"})
        with self.assertRaises(store.Refused):
            store.save("nope", {})

    def test_unlock_by_deleting_failures(self):
        db.execute("INSERT INTO verify_failures (identity, failed_at) VALUES ('1509900543223', '2026-01-01 00:00:00')")
        row = self.table("verify_failures")["rows"][0]
        store.delete("verify_failures", row["id"])
        self.assertEqual(self.table("verify_failures")["rows"], [])

    def test_reset_brings_back_the_demo(self):
        store.delete("loans", "HL6201234567")
        store.save("faq", {"answer": "แก้แล้ว"}, "late_fee")
        store.save("sn_customerservice_case", {"short_description": "x"})
        store.reset()
        self.assertEqual(len(self.table("loans")["rows"]), 10)
        faq = {r["topic"]: r for r in self.table("faq")["rows"]}
        self.assertNotEqual(faq["late_fee"]["answer"], "แก้แล้ว")
        self.assertEqual([r["number"] for r in self.table("sn_customerservice_case")["rows"]], ["CS0001001"])


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
        self.assertEqual([t["name"] for t in data["tables"]][:4], ["customers", "customer_phones", "deposit_accounts", "credit_cards"])
        status, out = self.call("/api/save", {"table": "deposit_accounts", "row": {"account_no": "12", "national_id": PLOYSAI}})
        self.assertEqual(status, 400)
        status, out = self.call("/api/save", {"table": "deposit_accounts", "row": {
            "account_no": "5555555555", "national_id": PLOYSAI, "account_type": "ฝากประจำ", "balance": "100000"}})
        self.assertEqual((status, out["key"]), (200, "5555555555"))
        self.assertEqual(self.call("/api/delete", {"table": "deposit_accounts", "key": "5555555555"})[0], 200)
        self.assertEqual(self.call("/api/reset", {})[0], 200)

    def test_password_when_set(self):
        self.start(password="s3cret")
        self.assertEqual(self.call("/api/tables")[0], 401)
        auth = {"Authorization": "Basic " + base64.b64encode(b"admin:s3cret").decode()}
        self.assertEqual(self.call("/api/tables", headers=auth)[0], 200)


if __name__ == "__main__":
    unittest.main()
