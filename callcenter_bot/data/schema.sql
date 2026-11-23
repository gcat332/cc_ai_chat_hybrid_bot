-- Call-center tables. Safe to run on every start: nothing is dropped.

-- Bank customers, identified by the 13-digit national ID number (the bot's identity check).
-- Demo data only: a real bank keeps these in its core systems / ServiceNow.
CREATE TABLE IF NOT EXISTS customers (
    national_id TEXT PRIMARY KEY CHECK (length(national_id) = 13 AND national_id NOT GLOB '*[^0-9]*'),
    title       TEXT,                               -- นาย, นาง, นางสาว
    first_name  TEXT NOT NULL CHECK (first_name <> ''),
    last_name   TEXT,
    phone       TEXT CHECK (phone IS NULL OR (phone GLOB '0[0-9]*' AND length(phone) BETWEEN 9 AND 10)),
    segment     TEXT                                -- e.g. Mass, Wealth: who gets which service
);

-- More numbers a customer calls from (customers.phone is the main one). A call from any of them
-- needs only the last 4 ID digits. One number belongs to one customer.
CREATE TABLE IF NOT EXISTS customer_phones (
    phone       TEXT PRIMARY KEY CHECK (phone GLOB '0[0-9]*' AND length(phone) BETWEEN 9 AND 10),
    national_id TEXT NOT NULL REFERENCES customers(national_id) ON UPDATE CASCADE ON DELETE CASCADE,
    note        TEXT                                -- e.g. มือถือเครื่องที่ 2, เบอร์ที่ทำงาน
);

CREATE TABLE IF NOT EXISTS deposit_accounts (
    account_no   TEXT PRIMARY KEY CHECK (length(account_no) = 10 AND account_no NOT GLOB '*[^0-9]*'),
    national_id  TEXT NOT NULL REFERENCES customers(national_id) ON UPDATE CASCADE ON DELETE CASCADE,
    account_type TEXT NOT NULL,                     -- ออมทรัพย์, ฝากประจำ, กระแสรายวัน
    balance      REAL NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ปกติ'
);

CREATE TABLE IF NOT EXISTS credit_cards (
    card_no          TEXT PRIMARY KEY CHECK (length(card_no) = 16 AND card_no NOT GLOB '*[^0-9]*'),
    national_id      TEXT NOT NULL REFERENCES customers(national_id) ON UPDATE CASCADE ON DELETE CASCADE,
    card_name        TEXT NOT NULL,                 -- e.g. Platinum
    credit_limit     REAL NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
    available_credit REAL NOT NULL DEFAULT 0,
    outstanding      REAL NOT NULL DEFAULT 0 CHECK (outstanding >= 0),     -- statement balance due
    minimum_due      REAL NOT NULL DEFAULT 0 CHECK (minimum_due >= 0),
    due_date         TEXT,                          -- YYYY-MM-DD
    status           TEXT NOT NULL DEFAULT 'ปกติ'    -- ปกติ, ระงับ, ยกเลิก
);

CREATE TABLE IF NOT EXISTS loans (
    loan_no               TEXT PRIMARY KEY CHECK (loan_no <> ''),
    national_id           TEXT NOT NULL REFERENCES customers(national_id) ON UPDATE CASCADE ON DELETE CASCADE,
    loan_type             TEXT NOT NULL,            -- สินเชื่อบ้าน, สินเชื่อส่วนบุคคล
    outstanding_principal REAL NOT NULL DEFAULT 0 CHECK (outstanding_principal >= 0),
    interest_rate         REAL,                     -- % per year
    monthly_installment   REAL NOT NULL DEFAULT 0 CHECK (monthly_installment >= 0),
    next_due_date         TEXT,                     -- YYYY-MM-DD
    remaining_months      INTEGER,
    status                TEXT NOT NULL DEFAULT 'ปกติ'
);

-- Cases (opened by agents), shaped like ServiceNow Customer Service Management's Case table
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
    consumer          TEXT,                                  -- ServiceNow: the consumer record. Here: national ID
    callback_phone    TEXT,                                  -- given by a customer who did not verify (custom field)
    order_id          TEXT,                                  -- the order it is about (custom field)
    close_notes       TEXT,                                  -- what the agent did, when resolved
    opened_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Failed identity checks, per national ID number and across conversations: after
-- config.VERIFY_LOCK_ATTEMPTS failures within config.VERIFY_LOCK_MINUTES, the bot stops checking
-- that number and hands over to an agent. Delete the rows to unlock it.
CREATE TABLE IF NOT EXISTS verify_failures (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    identity  TEXT NOT NULL,                 -- the national ID given, whether or not it is a customer
    failed_at TEXT NOT NULL                  -- Thai time, YYYY-MM-DD HH:MM:SS
);

-- Questions the rules answer from data: edit here (or on the data page), no code change needed.
-- action: answer = say it; handoff = say it, verify the customer, then pass them to an agent
--         (handoffReason = topic). The bot never opens cases itself ('offer_ticket' from older
--         databases is treated as handoff).
CREATE TABLE IF NOT EXISTS faq (
    topic    TEXT PRIMARY KEY CHECK (topic GLOB '[a-z]*' AND topic NOT GLOB '*[^a-z_]*'),
    title    TEXT NOT NULL CHECK (title <> ''),
    keywords TEXT NOT NULL CHECK (keywords <> ''),  -- comma-separated, matched like intents.py
    answer   TEXT NOT NULL CHECK (answer <> ''),
    action   TEXT NOT NULL DEFAULT 'answer' CHECK (action IN ('answer', 'handoff'))
);
