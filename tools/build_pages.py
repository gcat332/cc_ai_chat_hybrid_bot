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
    for page in ("index.html", "admin.html", "runtime.js"):
        shutil.copy(ROOT / "channels/webchat/static" / page, out / page)
    src = ROOT / "callcenter_bot"
    files = sorted(str(p.relative_to(src)) for p in [*src.glob("*.py"), *src.glob("data/*.sql")])
    for name in files:
        (bot_out / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / name, bot_out / name)
    (bot_out / "files.json").write_text(json.dumps(files))
    (out / ".nojekyll").touch()  # serve files as they are
    print(f"Built {out} with {len(files)} bot files")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "_site"))
