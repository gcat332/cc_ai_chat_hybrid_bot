"""Mock customer systems. Replace these functions with calls to your CRM / billing / order APIs.

Keep the same function names and return shapes and the rest of the bot does not change.
"""
import itertools
from datetime import date

_CUSTOMERS = {
    "0812345678": {"name": "สมชาย", "id_last4": "1234", "balance": 1250.50, "due": date(2026, 12, 5)},
    "0898765432": {"name": "สมหญิง", "id_last4": "5678", "balance": 0.0, "due": None},
}

_ORDERS = {
    "123456": {"status": "กำลังจัดส่ง", "carrier": "Kerry Express", "tracking": "KEX0099887766", "eta": date(2026, 11, 24)},
    "654321": {"status": "จัดส่งสำเร็จแล้ว", "carrier": "ไปรษณีย์ไทย", "tracking": "EF123456789TH", "eta": date(2026, 11, 18)},
    "111222": {"status": "กำลังเตรียมสินค้า", "carrier": None, "tracking": None, "eta": date(2026, 11, 27)},
}

_ticket_numbers = itertools.count(1001)


def find_customer(phone: str):
    """Customer record for a phone number, or None."""
    return _CUSTOMERS.get(phone)


def verify_customer(phone: str, id_last4: str) -> bool:
    """Check the last 4 digits of the national ID card against the record."""
    customer = _CUSTOMERS.get(phone)
    return bool(customer) and customer["id_last4"] == id_last4


def get_order(order_id: str):
    return _ORDERS.get(order_id)


def create_ticket(phone, description: str) -> str:
    """Open a support ticket and return its number."""
    return f"TK{next(_ticket_numbers)}"
