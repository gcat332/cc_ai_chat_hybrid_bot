"""The call center's database (SQLite, part of Python: nothing to install).

Server: a file, data/callcenter.db by default (set CALLCENTER_DB to move it). Created with the demo
rows in data/seed.sql the first time. GitHub Pages: the same tables run inside the browser and
reset when the page reloads.

Edit the rows on the admin page (`/admin`), or with any SQLite tool, e.g. DB Browser for SQLite.
"""
import os
import re
import sqlite3
import threading
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_PATH = os.environ.get("CALLCENTER_DB", str(HERE.parent / "data" / "callcenter.db"))
TICKET_OFFSET = 1000  # ticket id 1 is shown as TK1001

_conn = None
_lock = threading.RLock()


def use_database(path: str = DEFAULT_PATH, seed: bool = True) -> sqlite3.Connection:
    """Open (or create) the database at `path`. ":memory:" gives a fresh one, e.g. for tests."""
    global _conn
    with _lock:
        is_new = path == ":memory:" or not Path(path).exists()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript((HERE / "data" / "schema.sql").read_text(encoding="utf-8"))
        if is_new and seed:
            conn.executescript((HERE / "data" / "seed.sql").read_text(encoding="utf-8"))
        conn.commit()
        if _conn is not None:
            _conn.close()
        _conn = conn
        return conn


def _db() -> sqlite3.Connection:
    return _conn or use_database()


def query(sql: str, args=()) -> list:
    with _lock:
        return [dict(row) for row in _db().execute(sql, args)]


def execute(sql: str, args=()) -> int:
    """Run a change and commit it. Returns the new row id (for inserts)."""
    with _lock:
        conn = _db()
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid


# ---- Validation for edits from the admin page --------------------------------------------------
class InvalidRow(ValueError):
    """A row the tables would refuse; the message is shown to the admin in Thai."""


def _iso_date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise InvalidRow(f"{field}: ใช้รูปแบบวันที่ ปปปป-ดด-วว (ค.ศ.) เช่น 2026-12-05")


def save_customer(row: dict, old_phone: str = None):
    phone = re.sub(r"\D", "", str(row.get("phone", "")))
    if not re.fullmatch(r"0\d{8,9}", phone):
        raise InvalidRow("เบอร์โทรต้องเป็นตัวเลข 9–10 หลัก ขึ้นต้นด้วย 0")
    name = str(row.get("name", "")).strip()
    if not name:
        raise InvalidRow("กรุณาใส่ชื่อลูกค้า")
    id_last4 = str(row.get("id_last4", "")).strip()
    if not re.fullmatch(r"\d{4}", id_last4):
        raise InvalidRow("เลขบัตร 4 ตัวท้ายต้องเป็นตัวเลข 4 หลัก")
    try:
        balance = round(float(str(row.get("balance") or 0).replace(",", "")), 2)
    except ValueError:
        raise InvalidRow("ยอดค้างชำระต้องเป็นตัวเลข")
    if balance < 0:
        raise InvalidRow("ยอดค้างชำระติดลบไม่ได้")
    due = _iso_date(row.get("due_date"), "วันครบกำหนด")
    values = (phone, name, id_last4, balance, due)
    with _lock:
        if old_phone and old_phone != phone:
            if query("SELECT 1 FROM customers WHERE phone = ?", (phone,)):
                raise InvalidRow(f"มีลูกค้าเบอร์ {phone} อยู่แล้ว")
            execute("UPDATE customers SET phone=?, name=?, id_last4=?, balance=?, due_date=? WHERE phone=?",
                    values + (old_phone,))
        else:
            execute("INSERT INTO customers (phone, name, id_last4, balance, due_date) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(phone) DO UPDATE SET name=excluded.name, id_last4=excluded.id_last4, "
                    "balance=excluded.balance, due_date=excluded.due_date", values)
    return phone


def save_order(row: dict, old_id: str = None):
    order_id = str(row.get("order_id", "")).strip()
    if not re.fullmatch(r"\d{6}", order_id):
        raise InvalidRow("เลขคำสั่งซื้อต้องเป็นตัวเลข 6 หลัก")
    phone = re.sub(r"\D", "", str(row.get("phone") or "")) or None
    if phone and not query("SELECT 1 FROM customers WHERE phone = ?", (phone,)):
        raise InvalidRow(f"ไม่มีลูกค้าเบอร์ {phone} ในตารางลูกค้า")
    status = str(row.get("status", "")).strip()
    if not status:
        raise InvalidRow("กรุณาใส่สถานะคำสั่งซื้อ")
    values = (order_id, phone, status, str(row.get("carrier") or "").strip() or None,
              str(row.get("tracking") or "").strip() or None, _iso_date(row.get("eta"), "วันที่ได้รับ"))
    with _lock:
        if old_id and old_id != order_id:
            if query("SELECT 1 FROM orders WHERE order_id = ?", (order_id,)):
                raise InvalidRow(f"มีคำสั่งซื้อเลข {order_id} อยู่แล้ว")
            execute("UPDATE orders SET order_id=?, phone=?, status=?, carrier=?, tracking=?, eta=? "
                    "WHERE order_id=?", values + (old_id,))
        else:
            execute("INSERT INTO orders (order_id, phone, status, carrier, tracking, eta) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(order_id) DO UPDATE SET phone=excluded.phone, status=excluded.status, "
                    "carrier=excluded.carrier, tracking=excluded.tracking, eta=excluded.eta", values)
    return order_id


def save_ticket(row: dict):
    status = str(row.get("status", "")).strip()
    if not status:
        raise InvalidRow("กรุณาใส่สถานะ")
    execute("UPDATE tickets SET status = ? WHERE id = ?", (status, int(row["id"])))


def delete(table: str, key: str):
    column = {"customers": "phone", "orders": "order_id", "tickets": "id"}[table]
    execute(f"DELETE FROM {table} WHERE {column} = ?", (key,))


def all_tables() -> dict:
    return {
        "customers": query("SELECT * FROM customers ORDER BY name"),
        "orders": query("SELECT * FROM orders ORDER BY order_id"),
        "tickets": query(f"SELECT *, 'TK' || (id + {TICKET_OFFSET}) AS ticket_no FROM tickets ORDER BY id DESC"),
    }


# ---- Save/restore all rows (the GitHub Pages demo keeps them in the browser's storage) ---------
_TABLES = {"customers": ("phone", "name", "id_last4", "balance", "due_date"),
           "orders": ("order_id", "phone", "status", "carrier", "tracking", "eta"),
           "tickets": ("id", "phone", "description", "status", "created_at")}


def export_rows() -> dict:
    return {t: query(f"SELECT {', '.join(cols)} FROM {t}") for t, cols in _TABLES.items()}


def import_rows(data: dict):
    """Replace every row with `data` (from export_rows). All or nothing."""
    with _lock:
        conn = _db()
        try:
            for table in ("tickets", "orders", "customers"):
                conn.execute(f"DELETE FROM {table}")
            for table, cols in _TABLES.items():
                for row in data.get(table, []):
                    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 [row.get(c) for c in cols])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
