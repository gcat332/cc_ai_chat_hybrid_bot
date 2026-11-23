"""What the bot asks of the bank's systems. Reads the demo tables in db.py.

To use the real core banking / CRM / ServiceNow instead, rewrite these functions and keep their
names and return shapes: the rest of the bot does not change. The bot only reads (inquiries) and
checks identity; requests that open work are handed to agents.
"""
import uuid
from datetime import date, timedelta

from . import config, db


class CaseError(RuntimeError):
    """The case system could not answer: the bot hands over to a person. Raise it from get_case()
    when it is rewritten to call a real system."""


def _date(value):
    return date.fromisoformat(value[:10]) if value else None


# ---- customers and identity ---------------------------------------------------------------
def find_customer(national_id: str):
    """The customer with this national ID: {national_id, title, first_name, last_name, phone}, or None."""
    rows = db.query("SELECT national_id, title, first_name, last_name, phone, segment FROM customers "
                    "WHERE national_id = ?", (national_id,))
    return rows[0] if rows else None


def customer_by_phone(phone: str):
    """The one customer registered with this phone (main number or one in customer_phones), or None
    (none, or shared by several)."""
    rows = db.query("SELECT national_id, title, first_name, last_name, phone, segment FROM customers "
                    "WHERE phone = ? OR national_id IN (SELECT national_id FROM customer_phones WHERE phone = ?)",
                    (phone, phone))
    return rows[0] if len(rows) == 1 else None


# Lockout per ID number, across conversations. A real identity service may do this itself:
# then make verify_locked() return False and record_verify_failure() do nothing.
def _stamp(when) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def verify_locked(identity: str, now) -> bool:
    since = _stamp(now - timedelta(minutes=config.VERIFY_LOCK_MINUTES))
    rows = db.query("SELECT COUNT(*) AS n FROM verify_failures WHERE identity = ? AND failed_at >= ?",
                    (identity, since))
    return rows[0]["n"] >= config.VERIFY_LOCK_ATTEMPTS


def record_verify_failure(identity: str, now):
    db.execute("INSERT INTO verify_failures (identity, failed_at) VALUES (?, ?)", (identity, _stamp(now)))


def clear_verify_failures(identity: str):
    db.execute("DELETE FROM verify_failures WHERE identity = ?", (identity,))


# ---- products (inquiries) -----------------------------------------------------------------
def deposit_accounts(national_id: str) -> list:
    return db.query("SELECT account_no, account_type, balance, status FROM deposit_accounts "
                    "WHERE national_id = ? ORDER BY account_no", (national_id,))


def credit_cards(national_id: str) -> list:
    rows = db.query("SELECT card_no, card_name, credit_limit, available_credit, outstanding, minimum_due, "
                    "due_date, status FROM credit_cards WHERE national_id = ? ORDER BY card_no", (national_id,))
    return [{**r, "due_date": _date(r["due_date"])} for r in rows]


def loans(national_id: str) -> list:
    rows = db.query("SELECT loan_no, loan_type, outstanding_principal, interest_rate, monthly_installment, "
                    "next_due_date, remaining_months, status FROM loans WHERE national_id = ? ORDER BY loan_no",
                    (national_id,))
    return [{**r, "next_due_date": _date(r["next_due_date"])} for r in rows]


# ---- cases: the local table, shaped like ServiceNow's sn_customerservice_case ----------------
# This server does not call ServiceNow: Genesys owns that integration. For real cases, have Genesys
# look them up (its own Data Action) or rewrite get_case() against what the bank allows.
def create_case(short_description: str, category: str, *, consumer: str = None, callback_phone: str = None,
                order_id: str = None, contact_type: str = None, description: str = None) -> str:
    """Open a case and return its number (CS0001001, ...). The bot does not call this (requests go
    to agents); it is kept for the data pages and tests."""
    fields = {"short_description": short_description[:160], "description": description or short_description,
              "category": category, "contact_type": contact_type, "consumer": consumer,
              "callback_phone": callback_phone, "order_id": order_id}
    number = db.next_case_number()
    fields.update(sys_id=uuid.uuid4().hex, number=number)
    db.execute(f"INSERT INTO {db.CASE_TABLE} ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
               list(fields.values()))
    return number


def get_case(number: str):
    """The case with this number: {number, state, status, done, created, category, close_notes,
    consumer}, or None. `status` is what the bot tells the customer (config.CASE_STATES);
    `consumer` is whose case it is (the national ID; None when unknown)."""
    rows = db.query(f"SELECT number, state, opened_at, category, close_notes, consumer "
                    f"FROM {db.CASE_TABLE} WHERE number = ?", (number,))
    row = rows[0] if rows else None
    if not row:
        return None
    state = int(row["state"] or 0)
    return {"number": row["number"], "state": state, "status": config.CASE_STATES.get(state, "อยู่ระหว่างดำเนินการ"),
            "done": state in config.CASE_DONE_STATES, "created": _date(row.get("opened_at")),
            "category": row.get("category"), "close_notes": row.get("close_notes"), "consumer": row.get("consumer")}


def faq_entries() -> list:
    """Questions answered from the faq table: [{topic, title, keywords: [...], answer, action}]."""
    return [{**row, "keywords": [k.strip() for k in row["keywords"].split(",") if k.strip()]}
            for row in db.query("SELECT topic, title, keywords, answer, action FROM faq")]
