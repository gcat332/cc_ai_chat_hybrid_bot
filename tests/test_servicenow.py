"""Cases in ServiceNow (Table API), against a fake instance that answers like
/api/now/table/sn_customerservice_case. Also: old databases move their tickets to the case table."""
import base64
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from callcenter_bot import Bot, backend, config, db

config.AGENT_HOURS = None   # hours are tested in test_bot.FollowUpTest


class FakeServiceNow(BaseHTTPRequestHandler):
    cases, requests, fail = [], [], False

    def _reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, body=None):
        url = urllib.parse.urlparse(self.path)
        self.requests.append({"method": self.command, "path": url.path, "query": dict(urllib.parse.parse_qsl(url.query)),
                              "auth": self.headers.get("Authorization"), "body": body})
        return url

    def do_GET(self):
        url = self._record()
        if self.fail:
            return self._reply(500, {"error": {"message": "boom"}})
        query = dict(urllib.parse.parse_qsl(url.query))
        number = query.get("sysparm_query", "").removeprefix("number=")
        rows = [c for c in self.cases if c["number"] == number][:int(query.get("sysparm_limit", 10))]
        self._reply(200, {"result": rows})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._record(body)
        if self.fail:
            return self._reply(403, {"error": {"message": "no"}})
        case = {"sys_id": "a" * 32, "number": f"CS{len(self.cases) + 2000001:07d}", "state": "1",
                "opened_at": "2026-11-23 10:00:00", **body}
        self.cases.append(case)
        self._reply(201, {"result": {"sys_id": case["sys_id"], "number": case["number"]}})

    def log_message(self, *args):
        pass


class ServiceNowTest(unittest.TestCase):
    def setUp(self):
        db.use_database(":memory:")
        FakeServiceNow.cases, FakeServiceNow.requests, FakeServiceNow.fail = [], [], False
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeServiceNow)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        env = {"SERVICENOW_INSTANCE": f"http://127.0.0.1:{self.httpd.server_port}/",
               "SERVICENOW_USER": "bot", "SERVICENOW_PASSWORD": "pw"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.httpd.shutdown()
        self.httpd.server_close()

    def say(self, *lines, session="s"):
        bot = getattr(self, "bot", None) or Bot()
        self.bot = bot
        return [bot.reply(session, line) for line in lines][-1]

    def test_case_is_opened_in_servicenow(self):
        r = self.say("ยกเลิกออเดอร์ 111222", "ใช่", "0899999999")
        self.assertIn("CS2000001", r.text)                      # the number ServiceNow gave
        post = FakeServiceNow.requests[-1]
        self.assertEqual((post["method"], post["path"]), ("POST", "/api/now/table/sn_customerservice_case"))
        self.assertEqual(post["auth"], "Basic " + base64.b64encode(b"bot:pw").decode())
        body = post["body"]
        self.assertEqual((body["short_description"], body["category"], body["contact_type"]),
                         ("ขอยกเลิกคำสั่งซื้อ 111222", "order_cancel", "web"))
        # No standard field: written into the description, not sent as unknown fields.
        self.assertIn("เบอร์ติดต่อกลับ: 0899999999", body["description"])
        self.assertIn("เลขคำสั่งซื้อ: 111222", body["description"])
        self.assertNotIn("callback_phone", body)
        self.assertEqual(db.all_tables()[db.CASE_TABLE], [])     # nothing in the mock table

    def test_custom_fields_and_skipped_fields(self):
        with mock.patch.dict(os.environ, {"SERVICENOW_FIELD_MAP": "callback_phone=u_callback,order_id=u_order",
                                          "SERVICENOW_SKIP_FIELDS": "category"}):
            self.say("ยกเลิกออเดอร์ 111222", "ใช่", "0899999999")
        body = FakeServiceNow.requests[-1]["body"]
        self.assertEqual((body["u_callback"], body["u_order"]), ("0899999999", "111222"))
        self.assertNotIn("category", body)

    def test_case_status_is_read_from_servicenow(self):
        FakeServiceNow.cases.append({"sys_id": "b" * 32, "number": "CS0004567", "state": "18",
                                     "opened_at": "2026-11-20 09:00:00", "category": "report_problem"})
        r = self.say("เช็คเรื่อง CS0004567")
        self.assertIn("เรื่อง CS0004567 แจ้งเมื่อวันที่ 20 พฤศจิกายน สถานะ รอข้อมูลเพิ่มเติมจากลูกค้า", r.text)
        get = FakeServiceNow.requests[-1]
        self.assertEqual(get["query"]["sysparm_query"], "number=CS0004567")
        self.assertIn("ไม่พบเรื่อง", self.say("เช็คเรื่อง CS0009999", session="x").text)

    def test_servicenow_down_hands_over(self):
        FakeServiceNow.fail = True
        r = self.say("แจ้งปัญหา", "เน็ตหลุดบ่อยมาก", "ใช่", "0899999999")
        self.assertEqual((r.handoff, r.intent), (True, "case_error"))
        r = self.say("เช็คเรื่อง CS0001001", session="g")
        self.assertEqual((r.handoff, r.intent), (True, "case_error"))

    def test_unreachable_instance(self):
        with mock.patch.dict(os.environ, {"SERVICENOW_INSTANCE": "http://127.0.0.1:9", "SERVICENOW_TIMEOUT": "1"}):
            with self.assertRaises(backend.CaseError):
                backend.get_case("CS0001001")


class OldTicketsMoveTest(unittest.TestCase):
    def test_old_tickets_become_cases(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, description TEXT NOT NULL,
                                  status TEXT NOT NULL DEFAULT 'รอดำเนินการ', created_at TEXT);
            INSERT INTO tickets (phone, description, status, created_at) VALUES
                ('0812345678', 'เน็ตหลุด', 'รอดำเนินการ', '2026-11-01 10:00:00'),
                (NULL, 'ขอใบเสร็จ', 'เสร็จสิ้น', '2026-11-02 10:00:00');""")
        conn.commit()
        conn.close()
        db.use_database(str(path))
        cases = {c["number"]: c for c in db.all_tables()[db.CASE_TABLE]}
        self.assertEqual(set(cases), {"CS0001001", "CS0001002"})   # TK1001 -> CS0001001
        self.assertEqual((cases["CS0001001"]["consumer"], cases["CS0001001"]["state"]), ("0812345678", 1))
        self.assertEqual(cases["CS0001002"]["state"], 6)              # done -> Resolved
        self.assertEqual(db.next_case_number(), "CS0001003")
        self.assertFalse(db.query("SELECT 1 FROM sqlite_master WHERE name = 'tickets'"))
        db.use_database(":memory:")


if __name__ == "__main__":
    unittest.main()
