-- Call-center tables. Safe to run on every start: nothing is dropped.

CREATE TABLE IF NOT EXISTS customers (
    phone     TEXT PRIMARY KEY CHECK (phone GLOB '0[0-9]*' AND length(phone) BETWEEN 9 AND 10),
    name      TEXT NOT NULL CHECK (name <> ''),
    id_last4  TEXT NOT NULL CHECK (id_last4 GLOB '[0-9][0-9][0-9][0-9]'),  -- last 4 ID-card digits only
    balance   REAL NOT NULL DEFAULT 0 CHECK (balance >= 0),               -- outstanding, in baht
    due_date  TEXT                                                         -- YYYY-MM-DD, empty if nothing due
);

CREATE TABLE IF NOT EXISTS orders (
    order_id  TEXT PRIMARY KEY CHECK (order_id GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'),
    phone     TEXT REFERENCES customers(phone) ON UPDATE CASCADE ON DELETE SET NULL,
    status    TEXT NOT NULL,        -- e.g. กำลังเตรียมสินค้า, กำลังจัดส่ง, จัดส่งสำเร็จแล้ว
    carrier   TEXT,
    tracking  TEXT,
    eta       TEXT                  -- YYYY-MM-DD: expected, or delivered date
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- shown to customers as TK + (1000 + id)
    phone       TEXT,                                -- set when the customer was verified
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'รอดำเนินการ',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
