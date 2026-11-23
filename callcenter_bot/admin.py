"""Admin actions on the tables, shared by the web server and the in-browser (GitHub Pages) demo."""
from . import db

TABLES = ("customers", "orders", "tickets")


def save(table: str, row: dict, old_key=None) -> dict:
    """Add or update a row. Returns {"ok": True} or {"error": "<Thai message>"}."""
    try:
        if table == "customers":
            db.save_customer(row, old_key or None)
        elif table == "orders":
            db.save_order(row, old_key or None)
        elif table == "tickets":
            db.save_ticket(row)
        else:
            return {"error": "ไม่มีตารางนี้"}
    except db.InvalidRow as e:
        return {"error": str(e)}
    return {"ok": True}


def delete(table: str, key) -> dict:
    if table not in TABLES:
        return {"error": "ไม่มีตารางนี้"}
    db.delete(table, str(key))
    return {"ok": True}
