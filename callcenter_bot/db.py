"""The call center's database (SQLite, part of Python: nothing to install).

Server: a file, data/callcenter.db by default (set CALLCENTER_DB to move it). Created with the demo
rows in data/seed.sql the first time. GitHub Pages: the same tables run inside the browser and
reset when the page reloads.

Edit the rows on the data page (python -m dataadmin), the chat's admin page (`/admin`), or with any
SQLite tool. Checks for edits are in tables.py.
"""
import os
import sqlite3
import threading
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_PATH = os.environ.get("CALLCENTER_DB", str(HERE.parent / "data" / "callcenter.db"))
CASE_TABLE = "sn_customerservice_case"
CASE_PREFIX, CASE_DIGITS, CASE_FIRST = "CS", 7, 1001   # CS0001001, CS0001002, ...
# The bank's tables, in the order pages show them and in which rows are saved and restored.
TABLES = ("customers", "customer_phones", "deposit_accounts", "credit_cards", "loans", CASE_TABLE, "faq", "verify_failures")

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
        had_faq = _has_table(conn, "faq")
        if _drop_shop_demo(conn):
            is_new = True                  # the old demo's rows are gone: load the bank's
        conn.executescript((HERE / "data" / "schema.sql").read_text(encoding="utf-8"))
        _move_old_tickets(conn)
        if is_new and seed:
            conn.executescript((HERE / "data" / "seed.sql").read_text(encoding="utf-8"))
        if not had_faq and seed:   # new database, or one made before the faq table existed
            conn.executescript((HERE / "data" / "seed_faq.sql").read_text(encoding="utf-8"))
        conn.commit()
        if _conn is not None:
            _conn.close()
        _conn = conn
        return conn


def _has_table(conn, name) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _drop_shop_demo(conn) -> bool:
    """Databases from the first (online shop) demo: customers by phone, orders. Demo rows only, so
    they are dropped and the bank's demo rows loaded. Returns True when that happened."""
    dropped = False
    if _has_table(conn, "customers"):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(customers)")}
        if "national_id" not in columns:
            conn.execute("DROP TABLE IF EXISTS orders")
            conn.execute("DROP TABLE customers")
            dropped = True
    conn.execute("DROP TABLE IF EXISTS interaction")   # a stand-in kept briefly: Genesys sends transcripts now
    if _has_table(conn, "verify_failures"):
        if "identity" not in {row[1] for row in conn.execute("PRAGMA table_info(verify_failures)")}:
            conn.execute("DROP TABLE verify_failures")
    return dropped


def _move_old_tickets(conn: sqlite3.Connection):
    """Databases from before the case table kept requests in `tickets` (TK1001 ...): copy them
    into the case table (TK1001 becomes CS0001001) and drop the old table."""
    if not _has_table(conn, "tickets"):
        return
    have = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
    col = lambda name: name if name in have else "NULL"
    conn.execute(f"""
        INSERT OR IGNORE INTO {CASE_TABLE} (sys_id, number, short_description, description, state, category,
                                            consumer, callback_phone, order_id, opened_at)
        SELECT lower(hex(randomblob(16))), '{CASE_PREFIX}' || substr('0000000' || (1000 + id), -{CASE_DIGITS}),
               description, description,
               CASE status WHEN 'เสร็จสิ้น' THEN 6 WHEN 'กำลังดำเนินการ' THEN 10 ELSE 1 END,
               {col('category')}, phone, {col('callback_phone')}, {col('order_id')},
               COALESCE(created_at, datetime('now', 'localtime'))
        FROM tickets""")
    conn.execute("DROP TABLE tickets")


def next_case_number() -> str:
    """The next free case number: CS0001001 for the first."""
    rows = query(f"SELECT number FROM {CASE_TABLE} WHERE number LIKE ?", (CASE_PREFIX + "%",))
    used = [int(r["number"][len(CASE_PREFIX):]) for r in rows if r["number"][len(CASE_PREFIX):].isdigit()]
    return f"{CASE_PREFIX}{max(used + [CASE_FIRST - 1]) + 1:0{CASE_DIGITS}d}"


def case_number(digits) -> str:
    """What a customer said ("1001", "0001001") as a case number: CS0001001."""
    return f"{CASE_PREFIX}{int(digits):0{CASE_DIGITS}d}"


def reset_to_demo():
    """Delete every row and load the demo rows and example FAQ again."""
    with _lock:
        conn = _db()
        try:
            for table in reversed(TABLES):          # children before customers
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
            for script in ("seed.sql", "seed_faq.sql"):
                conn.executescript("BEGIN;" + (HERE / "data" / script).read_text(encoding="utf-8") + "COMMIT;")
        except Exception:
            conn.rollback()
            raise


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


def all_tables() -> dict:
    """Every bank table's rows, for the admin pages."""
    order = {CASE_TABLE: "number DESC", "verify_failures": "id DESC"}
    return {t: query(f"SELECT * FROM {t} ORDER BY {order.get(t, 'rowid')}") for t in TABLES}


# ---- Save/restore all rows (the GitHub Pages demo keeps them in the browser's storage) ---------
SAVE_VERSION = 2   # rows saved by the shop demo (version 1) are not restored


def export_rows() -> dict:
    return {"version": SAVE_VERSION, **{t: query(f"SELECT * FROM {t}") for t in TABLES if t != "verify_failures"}}


def import_rows(data: dict):
    """Replace every row with `data` (from export_rows). All or nothing."""
    if data.get("version") != SAVE_VERSION:
        return
    with _lock:
        conn = _db()
        try:
            for table in reversed(TABLES):
                if table in data:
                    conn.execute(f"DELETE FROM {table}")
            for table in TABLES:
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                for row in data.get(table, []):
                    cols = [c for c in row if c in columns]
                    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 [row[c] for c in cols])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
