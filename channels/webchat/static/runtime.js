// Runs the bot for the chat page and the admin page, in one of two ways:
// * server mode: channels/webchat/server.py answers at api/ (real database file, production)
// * browser mode: no server (GitHub Pages). The Python bot and its SQLite tables run inside the
//   page with Pyodide. Changes are kept in this browser's storage, so the chat page and the admin
//   page see the same rows, and they survive a reload. Demo only: nothing reaches a server.
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/";
const STORE_KEY = "callcenter_db_v1";

async function hasServer() {
  try { return (await fetch("api/health")).ok; } catch { return false; }
}

async function loadPython() {
  await new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = PYODIDE_URL + "pyodide.js"; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  const files = await (await fetch("callcenter_bot/files.json")).json();
  for (const f of files) {
    const path = "/app/callcenter_bot/" + f;
    py.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    py.FS.writeFile(path, await (await fetch("callcenter_bot/" + f)).text());
  }
  py.runPython(`import sys; sys.path.insert(0, "/app")`);
  const mod = py.pyimport("callcenter_bot.browser");
  const saved = localStorage.getItem(STORE_KEY);
  if (saved) {
    try { mod.import_rows(saved); } catch { localStorage.removeItem(STORE_KEY); }  // unreadable: start fresh
  }
  return mod;
}

async function startRuntime() {
  if (await hasServer()) {
    const post = async (path, body) => {
      const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || `ระบบตอบกลับผิดพลาด (${r.status})`);
      return data;
    };
    return {
      mode: "server",
      start: sid => post("api/start", { session_id: sid }),
      chat: (sid, message) => post("api/chat", { session_id: sid, message }),
      tables: async () => {
        const r = await fetch("api/admin/tables");
        if (!r.ok) throw new Error(r.status === 403 ? await r.text() : `โหลดข้อมูลไม่สำเร็จ (${r.status})`);
        return r.json();
      },
      save: (table, row, oldKey) => post("api/admin/save", { table, row, old_key: oldKey ?? null }),
      remove: (table, key) => post("api/admin/delete", { table, key }),
    };
  }

  const py = await loadPython();
  const persist = () => localStorage.setItem(STORE_KEY, py.export_rows());
  const checked = json => {
    const data = JSON.parse(json);
    if (data.error) throw new Error(data.error);
    persist();
    return data;
  };
  return {
    mode: "browser",
    start: async sid => JSON.parse(py.start(sid)),
    chat: async (sid, message) => {
      const reply = JSON.parse(py.chat(sid, message));
      persist();  // e.g. a new ticket
      return reply;
    },
    tables: async () => JSON.parse(py.tables()),
    save: async (table, row, oldKey) => checked(py.save(table, JSON.stringify(row), oldKey ?? null)),
    remove: async (table, key) => checked(py.delete(table, String(key))),
    reset: async () => { localStorage.removeItem(STORE_KEY); py.reset_demo(); },
    // Another tab (chat or admin) changed the rows: load them here too.
    reload: async () => { const saved = localStorage.getItem(STORE_KEY); if (saved) py.import_rows(saved); },
  };
}
