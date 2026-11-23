"""What the bot asks of the company's systems. Reads and writes the tables in db.py.

To use your real CRM / billing / order systems instead, rewrite these four functions and keep
their names and return shapes: the rest of the bot does not change.
"""
from datetime import date

from . import db


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


def create_ticket(phone, description: str) -> str:
    """Open a support ticket and return its number."""
    ticket_id = db.execute("INSERT INTO tickets (phone, description) VALUES (?, ?)", (phone, description))
    return f"TK{ticket_id + db.TICKET_OFFSET}"
