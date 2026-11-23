"""Assemble the static GitHub Pages site: the chat page plus the bot's Python files,
which the page runs in the browser with Pyodide.

    python tools/build_pages.py _site
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path):
    if out.exists():
        shutil.rmtree(out)
    bot_out = out / "callcenter_bot"
    bot_out.mkdir(parents=True)
    shutil.copy(ROOT / "channels/webchat/static/index.html", out / "index.html")
    files = sorted(p.name for p in (ROOT / "callcenter_bot").glob("*.py"))
    for name in files:
        shutil.copy(ROOT / "callcenter_bot" / name, bot_out / name)
    (bot_out / "files.json").write_text(json.dumps(files))
    (out / ".nojekyll").touch()  # serve files as they are
    print(f"Built {out} with {len(files)} bot files")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "_site"))
