"""Thai formatting for dates, money and masked numbers."""

MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def thai_date(d) -> str:
    """date(2026, 12, 5) -> "5 ธันวาคม 2569" (Buddhist year)."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year + 543}"


def baht(amount: float) -> str:
    return f"{amount:,.2f} บาท"


def mask_phone(phone: str) -> str:
    """"0812345678" -> "081-xxx-5678", safe to show and log."""
    return f"{phone[:3]}-xxx-{phone[-4:]}" if phone and len(phone) >= 7 else "xxx"
