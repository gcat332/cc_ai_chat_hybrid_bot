"""Entry points for the GitHub Pages demo, where Python runs inside the browser (Pyodide).
Everything is passed as JSON strings. The tables live in memory; the page saves them to the
browser's storage after each change and restores them on the next visit."""
import json

from . import admin, db
from .bot import Bot

db.use_database(":memory:")
_bot = Bot()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def chat(session_id: str, message: str) -> str:
    return _json({"session_id": session_id, **_bot.reply(session_id, message).to_dict()})


def start(session_id: str) -> str:
    _bot.reset(session_id)
    return _json({"session_id": session_id, **_bot.welcome().to_dict()})


def tables() -> str:
    return _json(db.all_tables())


def save(table: str, row_json: str, old_key) -> str:
    return _json(admin.save(table, json.loads(row_json), old_key))


def delete(table: str, key) -> str:
    return _json(admin.delete(table, key))


def export_rows() -> str:
    return _json(db.export_rows())


def import_rows(data: str):
    db.import_rows(json.loads(data))


def reset_demo():
    """Back to the demo rows."""
    db.use_database(":memory:")
