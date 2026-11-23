"""Read and edit every table of the database, for the data pages (python -m dataadmin, the chat's
/admin, and the GitHub Pages demo).

Tables and columns come from the database itself (PRAGMA table_info), so a column or table added
to data/schema.sql shows up with no change here. Each edit is checked first; refusals carry a
Thai message for the page.
"""
import re
import sqlite3
import uuid
from datetime import date

from . import db

FAQ_ACTIONS = ("answer", "handoff")
DATE_COLUMNS = {"due_date", "next_due_date"}
NUMBER_LABELS = {"balance": "ยอดเงิน", "credit_limit": "วงเงิน", "available_credit": "วงเงินคงเหลือ",
                 "outstanding": "ยอดค้างชำระ", "minimum_due": "ยอดชำระขั้นต่ำ",
                 "outstanding_principal": "ยอดหนี้คงเหลือ", "monthly_installment": "ค่างวด",
                 "interest_rate": "อัตราดอกเบี้ย", "remaining_months": "จำนวนงวดที่เหลือ"}


class Refused(ValueError):
    """An edit the page should show as a Thai message instead of saving."""


def valid_national_id(value: str) -> bool:
    """13 digits whose last digit is the Thai national ID checksum."""
    if not re.fullmatch(r"\d{13}", value or ""):
        return False
    digits = [int(c) for c in value]
    return (11 - sum(d * (13 - i) for i, d in enumerate(digits[:12])) % 11) % 10 == digits[12]


def table_names() -> list:
    names = [r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return [n for n in db.TABLES if n in names] + sorted(n for n in names if n not in db.TABLES)


def _check_table(table: str):
    if table not in table_names():
        raise Refused("ไม่มีตารางนี้")


def columns(table: str) -> list:
    _check_table(table)
    return [{"name": c["name"], "type": (c["type"] or "TEXT").upper(), "required": bool(c["notnull"]),
             "key": bool(c["pk"]), "default": c["dflt_value"]}
            for c in db.query(f'PRAGMA table_info("{table}")')]


def key_column(table: str) -> str:
    keys = [c["name"] for c in columns(table) if c["key"]]
    return keys[0] if keys else "rowid"


def snapshot() -> list:
    """Every table with its columns and rows, for the data page."""
    rows = db.all_tables()
    out = []
    for table in table_names():
        out.append({"name": table, "key": key_column(table), "columns": columns(table),
                    "rows": rows.get(table) if table in rows else db.query(f'SELECT * FROM "{table}"')})
    return out


def _clean(row: dict, cols: list) -> dict:
    """Only real columns; empty strings become NULL; numbers become numbers; digits-only IDs lose
    their spaces and dashes."""
    out = {}
    for c in cols:
        if c["name"] not in row:
            continue
        value = row[c["name"]]
        if isinstance(value, str):
            value = value.strip()
            if c["name"] in ("national_id", "phone", "account_no", "card_no"):
                value = re.sub(r"[\s-]", "", value)
        if value == "":
            value = None
        if value is not None and c["type"] in ("REAL", "INTEGER"):
            try:
                value = float(str(value).replace(",", "")) if c["type"] == "REAL" else int(value)
            except ValueError:
                raise Refused(f"{NUMBER_LABELS.get(c['name'], c['name'])}: ต้องเป็นตัวเลข")
        if value is not None and c["name"] in DATE_COLUMNS:
            try:
                value = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise Refused("วันที่: ใช้รูปแบบ ปปปป-ดด-วว (ค.ศ.) เช่น 2026-12-05")
        out[c["name"]] = value
    return out


def _check(table: str, row: dict):
    """Rules per table, on the row as it will be saved."""
    if row.get("national_id") is not None and table in ("customers", "customer_phones", "deposit_accounts",
                                                         "credit_cards", "loans"):
        if not valid_national_id(row["national_id"]):
            raise Refused("เลขบัตรประชาชนต้องเป็นตัวเลข 13 หลักที่ถูกต้อง")
        if table != "customers" and not db.query("SELECT 1 FROM customers WHERE national_id = ?",
                                                 (row["national_id"],)):
            raise Refused("ไม่มีลูกค้าเลขบัตรนี้ในตารางลูกค้า")
    if table == "customers":
        if not row.get("first_name"):
            raise Refused("กรุณาใส่ชื่อลูกค้า")
        if row.get("phone") and not re.fullmatch(r"0\d{8,9}", row["phone"]):
            raise Refused("เบอร์โทรต้องเป็นตัวเลข 9–10 หลัก ขึ้นต้นด้วย 0")
    if table == "customer_phones":
        if not re.fullmatch(r"0\d{8,9}", row.get("phone") or ""):
            raise Refused("เบอร์โทรต้องเป็นตัวเลข 9–10 หลัก ขึ้นต้นด้วย 0")
        owner = db.query("SELECT national_id FROM customers WHERE phone = ?", (row["phone"],))
        if owner and owner[0]["national_id"] != row.get("national_id"):
            raise Refused("เบอร์นี้เป็นเบอร์หลักของลูกค้าคนอื่นแล้ว")
    if table == "deposit_accounts" and not re.fullmatch(r"\d{10}", row.get("account_no") or ""):
        raise Refused("เลขบัญชีต้องเป็นตัวเลข 10 หลัก")
    if table == "credit_cards" and not re.fullmatch(r"\d{16}", row.get("card_no") or ""):
        raise Refused("เลขบัตรเครดิตต้องเป็นตัวเลข 16 หลัก")
    for name in ("credit_limit", "outstanding", "minimum_due", "outstanding_principal", "monthly_installment"):
        if (row.get(name) or 0) < 0:
            raise Refused(f"{NUMBER_LABELS[name]}ติดลบไม่ได้")
    if table == db.CASE_TABLE and not row.get("short_description"):
        raise Refused("กรุณาใส่หัวเรื่อง (short_description)")
    if table == "faq":
        if not re.fullmatch(r"[a-z][a-z_]*", row.get("topic") or ""):
            raise Refused("topic: ใช้ตัวอักษรอังกฤษพิมพ์เล็กและ _ เท่านั้น เช่น late_fee")
        for name, label in (("title", "หัวข้อ"), ("keywords", "คำที่ลูกค้าพูด"), ("answer", "คำตอบ")):
            if not row.get(name):
                raise Refused(f"กรุณาใส่{label}")
        if row.get("action") not in FAQ_ACTIONS:
            raise Refused("หลังตอบ ต้องเป็น answer (ตอบอย่างเดียว) หรือ handoff (โอนเจ้าหน้าที่)")


def save(table: str, row: dict, old_key=None):
    """Add a row (old_key empty) or update the row whose key is old_key. Returns its key
    (the case number for a new case)."""
    _check_table(table)
    cols = columns(table)
    key = key_column(table)
    values = _clean(row, cols)
    is_new = old_key in (None, "")
    if table == "verify_failures":
        values.pop("id", None)
    if table == db.CASE_TABLE and is_new:          # numbered like ServiceNow: sys_id and CS0001001
        values["sys_id"] = values.get("sys_id") or uuid.uuid4().hex
        values["number"] = values.get("number") or db.next_case_number()
    whole = dict(values)                           # the row as it will be: an edit may send a few columns
    if not is_new:
        existing = db.query(f'SELECT * FROM "{table}" WHERE "{key}" = ?', (old_key,))
        if not existing:
            raise Refused("ไม่พบแถวนี้ อาจถูกลบไปแล้ว กดโหลดใหม่")
        whole = {**existing[0], **values}
    if table == "faq":
        whole["action"] = whole.get("action") or "answer"
        values["action"] = whole["action"]
    _check(table, whole)
    missing = [c["name"] for c in cols if c["required"] and c["default"] is None and not c["key"]
               and whole.get(c["name"]) is None]
    if missing:
        raise Refused("กรุณากรอก: " + ", ".join(missing))
    try:
        if not is_new:
            if values:
                assignments = ", ".join(f'"{name}" = ?' for name in values)
                db.execute(f'UPDATE "{table}" SET {assignments} WHERE "{key}" = ?', [*values.values(), old_key])
            return values.get(key, old_key)
        names = ", ".join(f'"{name}"' for name in values)
        new_id = db.execute(f'INSERT INTO "{table}" ({names}) VALUES ({", ".join("?" * len(values))})',
                            list(values.values()))
        return values.get("number") if table == db.CASE_TABLE else values.get(key, new_id)
    except sqlite3.IntegrityError as e:
        text = str(e)
        if "UNIQUE" in text:
            raise Refused(f"มี {key} นี้อยู่แล้ว")
        if "FOREIGN KEY" in text:
            raise Refused("ข้อมูลอ้างถึงแถวที่ไม่มีอยู่")
        raise Refused(f"บันทึกไม่ได้: ข้อมูลไม่ผ่านเงื่อนไขของตาราง ({text})")


def delete(table: str, key):
    _check_table(table)
    try:
        db.execute(f'DELETE FROM "{table}" WHERE "{key_column(table)}" = ?', (key,))
    except sqlite3.IntegrityError:
        raise Refused("ลบไม่ได้: ยังมีข้อมูลอื่นอ้างถึงแถวนี้")


def reset():
    db.reset_to_demo()
