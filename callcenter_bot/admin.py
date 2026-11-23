"""Admin actions on the tables, shared by the web server and the in-browser (GitHub Pages) demo."""
from . import tables


def save(table: str, row: dict, old_key=None) -> dict:
    """Add or update a row. Returns {"ok": True} or {"error": "<Thai message>"}."""
    try:
        tables.save(table, row, old_key or None)
    except tables.Refused as e:
        return {"error": str(e)}
    return {"ok": True}


def delete(table: str, key) -> dict:
    try:
        tables.delete(table, key)
    except tables.Refused as e:
        return {"error": str(e)}
    return {"ok": True}
