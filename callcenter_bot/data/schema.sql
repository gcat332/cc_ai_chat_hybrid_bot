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

-- Cases the bot opens, shaped like ServiceNow Customer Service Management's Case table
-- [sn_customerservice_case]: same table and field names, so the bot can move to the real
-- instance (callcenter_bot/servicenow.py) without changing what it reads and writes.
CREATE TABLE IF NOT EXISTS sn_customerservice_case (
    sys_id            TEXT PRIMARY KEY,                      -- 32 hex characters, as in ServiceNow
    number            TEXT NOT NULL UNIQUE,                  -- CS0001001: the number customers are told
    short_description TEXT NOT NULL CHECK (short_description <> ''),
    description       TEXT,
    state             INTEGER NOT NULL DEFAULT 1,            -- config.CASE_STATES: 1 New, 10 Open,
                                                             -- 18 Awaiting Info, 6 Resolved, 3 Closed, 7 Cancelled
    priority          INTEGER NOT NULL DEFAULT 4,            -- 1 Critical, 2 High, 3 Moderate, 4 Low
    category          TEXT,                                  -- report_problem, order_cancel, callback, ...
    contact_type      TEXT,                                  -- channel: phone, web
    consumer          TEXT,                                  -- ServiceNow: the consumer record. Here: verified phone
    callback_phone    TEXT,                                  -- given by a customer who did not verify (custom field)
    order_id          TEXT,                                  -- the order it is about (custom field)
    close_notes       TEXT,                                  -- what the agent did, when resolved
    opened_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Questions the rules answer from data: edit here (or on the data page), no code change needed.
-- action: answer = say it; offer_ticket = say it, then offer to open a ticket;
--         handoff = say it, then pass the customer to an agent (handoffReason = topic).
CREATE TABLE IF NOT EXISTS faq (
    topic    TEXT PRIMARY KEY CHECK (topic GLOB '[a-z]*' AND topic NOT GLOB '*[^a-z_]*'),
    title    TEXT NOT NULL CHECK (title <> ''),
    keywords TEXT NOT NULL CHECK (keywords <> ''),  -- comma-separated, matched like intents.py
    answer   TEXT NOT NULL CHECK (answer <> ''),
    action   TEXT NOT NULL DEFAULT 'answer' CHECK (action IN ('answer', 'offer_ticket', 'handoff'))
);
