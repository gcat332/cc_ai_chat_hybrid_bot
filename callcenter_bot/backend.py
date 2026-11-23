"""What the bot asks of the company's systems. Reads and writes the tables in db.py.

To use your real CRM / billing / order systems instead, rewrite these functions and keep
their names and return shapes: the rest of the bot does not change.
"""
import uuid
from datetime import date

from . import config, db, servicenow
from .servicenow import CaseError  # noqa: F401  (the bot catches it)


def _date(value):
    return date.fromisoformat(value) if value else None


def find_customer(phone: str):
    """Customer record for a phone number, or None."""
    rows = db.query("SELECT name, id_last4, balance, due_date FROM customers WHERE phone = ?", (phone,))
    if not rows:
        return None
    c = rows[0]
    return {"name": c["name"], "id_last4": c["id_last4"], "balance": c["balance"], "due": _date(c["due_date"])}


def verify_customer(phone: str, id_last4: str) -> bool:
    """Check the last 4 digits of the national ID card against the record."""
    customer = find_customer(phone)
    return bool(customer) and customer["id_last4"] == id_last4


def get_order(order_id: str):
    rows = db.query("SELECT status, carrier, tracking, eta FROM orders WHERE order_id = ?", (order_id,))
    if not rows:
        return None
    o = rows[0]
    return {"status": o["status"], "carrier": o["carrier"], "tracking": o["tracking"], "eta": _date(o["eta"])}


def create_case(short_description: str, category: str, *, consumer: str = None, callback_phone: str = None,
                order_id: str = None, contact_type: str = None, description: str = None) -> str:
    """Open a case and return its number (CS0001001, ...). `consumer` is the verified customer's
    phone; `callback_phone` a number given by a customer who did not verify.
    Goes to ServiceNow when SERVICENOW_INSTANCE is set, else to the local mock table.
    Raises CaseError when ServiceNow cannot be reached."""
    fields = {"short_description": short_description[:160], "description": description or short_description,
              "category": category, "contact_type": contact_type, "consumer": consumer,
              "callback_phone": callback_phone, "order_id": order_id}
    if servicenow.configured():
        return servicenow.create_case(fields)
    number = db.next_case_number()
    fields.update(sys_id=uuid.uuid4().hex, number=number)
    names = ", ".join(fields)
    db.execute(f"INSERT INTO {db.CASE_TABLE} ({names}) VALUES ({', '.join('?' * len(fields))})", list(fields.values()))
    return number


def get_case(number: str):
    """The case with this number: {number, state, status, done, created, category, order_id}, or None.
    `status` is what the bot tells the customer (config.CASE_STATES)."""
    if servicenow.configured():
        row = servicenow.get_case(number)
    else:
        rows = db.query(f"SELECT number, state, opened_at, category, close_notes, order_id FROM {db.CASE_TABLE} "
                        "WHERE number = ?", (number,))
        row = rows[0] if rows else None
    if not row:
        return None
    state = int(row["state"] or 0)
    opened = (row["opened_at"] or "")[:10]
    return {"number": row["number"], "state": state, "status": config.CASE_STATES.get(state, "อยู่ระหว่างดำเนินการ"),
            "done": state in config.CASE_DONE_STATES, "created": _date(opened) if opened else None,
            "category": row["category"], "order_id": row["order_id"]}


def faq_entries() -> list:
    """Questions answered from the faq table: [{topic, title, keywords: [...], answer, action}]."""
    return [{**row, "keywords": [k.strip() for k in row["keywords"].split(",") if k.strip()]}
            for row in db.query("SELECT topic, title, keywords, answer, action FROM faq")]
