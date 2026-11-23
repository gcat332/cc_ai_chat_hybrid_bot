"""Read and edit every table of the bot's SQLite database, for the mock-data page.

Tables and columns come from the database itself (PRAGMA table_info), so a column or table added
to callcenter_bot/data/schema.sql shows up here with no change. Customers and orders keep the
checks the chat admin page uses (db.save_customer / db.save_order); the rest get simple checks here.
"""
import re
import sqlite3
import uuid

from callcenter_bot import db

# Shown first, in this order; any other table in the database follows.
ORDER = ("customers", "orders", db.CASE_TABLE, "faq")
FAQ_ACTIONS = ("answer", "offer_ticket", "handoff")


class Refused(ValueError):
    """An edit the page should show as a Thai message instead of saving."""


def table_names() -> list:
    names = [r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return [n for n in ORDER if n in names] + sorted(n for n in names if n not in ORDER)


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
    """Every table with its columns and rows, for the page."""
    out = []
    for table in table_names():
        key = key_column(table)
        order = '"number" DESC' if table == db.CASE_TABLE else f'"{key}"'
        out.append({"name": table, "key": key, "columns": columns(table),
                    "rows": db.query(f'SELECT * FROM "{table}" ORDER BY {order}')})
    return out


def _clean(row: dict, cols: list) -> dict:
    """Only real columns; empty strings become NULL; numbers become numbers."""
    out = {}
    for c in cols:
        if c["name"] not in row:
            continue
        value = row[c["name"]]
        if isinstance(value, str):
            value = value.strip()
        if value == "":
            value = None
        if value is not None and c["type"] in ("REAL", "INTEGER"):
            try:
                value = float(str(value).replace(",", "")) if c["type"] == "REAL" else int(value)
            except ValueError:
                raise Refused(f"{c['name']}: ต้องเป็นตัวเลข")
        out[c["name"]] = value
    return out


def _check_faq(row: dict):
    if not re.fullmatch(r"[a-z][a-z_]*", row.get("topic") or ""):
        raise Refused("topic: ใช้ตัวอักษรอังกฤษพิมพ์เล็กและ _ เท่านั้น เช่น late_fee")
    for name, label in (("title", "หัวข้อ"), ("keywords", "คำที่ลูกค้าพูด"), ("answer", "คำตอบ")):
        if not row.get(name):
            raise Refused(f"กรุณาใส่{label}")
    if row.get("action", "answer") not in FAQ_ACTIONS:
        raise Refused("action ต้องเป็น answer, offer_ticket หรือ handoff")


def save(table: str, row: dict, old_key=None):
    """Add a row (old_key empty) or update the row whose key is old_key."""
    _check_table(table)
    try:
        if table == "customers":
            return db.save_customer(row, old_key or None)
        if table == "orders":
            return db.save_order(row, old_key or None)
    except db.InvalidRow as e:
        raise Refused(str(e))
    cols = columns(table)
    key = key_column(table)
    values = _clean(row, cols)
    new_case = table == db.CASE_TABLE and old_key in (None, "")
    if new_case:                            # numbered like ServiceNow: sys_id and CS0001001
        values["sys_id"] = values.get("sys_id") or uuid.uuid4().hex
        values["number"] = values.get("number") or db.next_case_number()
    # Check the row as it will be: an edit may send only the columns it changes.
    whole = dict(values)
    if old_key not in (None, ""):
        existing = db.query(f'SELECT * FROM "{table}" WHERE "{key}" = ?', (old_key,))
        if not existing:
            raise Refused("ไม่พบแถวนี้ อาจถูกลบไปแล้ว กดโหลดใหม่")
        whole = {**existing[0], **values}
    if table == "faq":
        whole["action"] = whole.get("action") or "answer"
        values.setdefault("action", whole["action"])
        _check_faq(whole)
    if table == db.CASE_TABLE and not whole.get("short_description"):
        raise Refused("กรุณาใส่หัวเรื่อง (short_description)")
    missing = [c["name"] for c in cols if c["required"] and c["default"] is None and not c["key"]
               and values.get(c["name"]) is None and not old_key]
    if missing:
        raise Refused("กรุณากรอก: " + ", ".join(missing))
    try:
        if old_key not in (None, ""):
            if not values:
                return old_key
            assignments = ", ".join(f'"{name}" = ?' for name in values)
            db.execute(f'UPDATE "{table}" SET {assignments} WHERE "{key}" = ?', [*values.values(), old_key])
            return values.get(key, old_key)
        names = ", ".join(f'"{name}"' for name in values)
        new_id = db.execute(f'INSERT INTO "{table}" ({names}) VALUES ({", ".join("?" * len(values))})',
                            list(values.values()))
        return values.get("number") if new_case else values.get(key, new_id)
    except sqlite3.IntegrityError as e:
        text = str(e)
        if "UNIQUE" in text:
            raise Refused(f"มี {key} นี้อยู่แล้ว")
        if "FOREIGN KEY" in text:
            raise Refused("ข้อมูลอ้างถึงแถวที่ไม่มีอยู่ (เช่น เบอร์ที่ไม่มีในตารางลูกค้า)")
        raise Refused(f"บันทึกไม่ได้: ข้อมูลไม่ผ่านเงื่อนไขของตาราง ({text})")


def delete(table: str, key):
    _check_table(table)
    try:
        db.execute(f'DELETE FROM "{table}" WHERE "{key_column(table)}" = ?', (key,))
    except sqlite3.IntegrityError:
        raise Refused("ลบไม่ได้: ยังมีข้อมูลอื่นอ้างถึงแถวนี้")


def reset():
    db.reset_to_demo()
