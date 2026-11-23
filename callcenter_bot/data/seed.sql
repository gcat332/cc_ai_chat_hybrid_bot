-- Demo data for the bank POC, loaded only when a new database is created.
-- Made-up people and numbers (the national IDs pass the checksum but belong to no one real).
INSERT INTO customers (national_id, title, first_name, last_name, phone, segment) VALUES
    ('3294367792962', 'นางสาว', 'พลอยใส', 'ใจดี',   '0815493626', 'Mass'),
    ('1101700123456', 'นาย',    'สมชาย', 'ใจงาม',  '0812345678', 'Wealth'),
    ('3100500678905', 'นาง',    'วิภา',   'รักษ์ดี', '0861112233', 'Mass'),
    ('1509900543215', 'นาย',    'ทดสอบ', 'ระบบ',   '0636538939', 'Mass'),   -- test number
    -- The KTB PayOff PoC's six scenarios, as in ServiceNow's Core Banking mock (customer_ref PHL-C1..C6,
    -- consumer phl.cN@mailsac.com). Same names (no title, as the ServiceNow consumer), phones (the ANI)
    -- and loans, so ServiceNow's PayOff flow finds the caller. Keep in step with that mock.
    ('1100800000011', NULL, 'สมชาย', 'ทดสอบ', '0810000001', 'Mass'),    -- C1_URGENT: must close within 5 days
    ('1100800000029', NULL, 'สมหญิง', 'ทดสอบ', '0810000002', 'Mass'),   -- C2_STANDARD
    ('1100800000037', NULL, 'วิชัย', 'ทดสอบ', '0810000003', 'VIP'),      -- C3_VIP
    ('1100800000045', NULL, 'มานี', 'ทดสอบ', '0810000004', 'Mass'),      -- C4_NOT_ACTIVE: loan already closed
    ('1100800000053', NULL, 'ปิติ', 'ทดสอบ', '0810000005', 'Wealth'),    -- C5_HIGH_LTV
    ('1100800000061', NULL, 'ชูใจ', 'ทดสอบ', '0810000006', 'Mass');      -- C6_CB_DOWN (ServiceNow side)

-- นางสาวพลอยใส ใจดี also calls from a second mobile.
INSERT INTO customer_phones (phone, national_id, note) VALUES
    ('0875679673', '3294367792962', 'มือถือเครื่องที่ 2');

INSERT INTO deposit_accounts (account_no, national_id, account_type, balance) VALUES
    ('1234567890', '3294367792962', 'ออมทรัพย์', 85420.50),
    ('2345678901', '1101700123456', 'ออมทรัพย์', 1250000.00),
    ('2345678912', '1101700123456', 'ฝากประจำ',  3000000.00),
    ('3456789012', '3100500678905', 'ออมทรัพย์', 12350.75),
    ('4567890123', '1509900543215', 'ออมทรัพย์', 5200.00);

INSERT INTO credit_cards (card_no, national_id, card_name, credit_limit, available_credit, outstanding, minimum_due, due_date) VALUES
    ('4532123412347788', '3294367792962', 'Platinum', 150000, 112450, 37550, 3755, '2026-12-10'),
    ('4532987698761234', '1101700123456', 'Signature', 500000, 482300, 17700, 1770, '2026-12-15'),
    ('5412000011112222', '1509900543215', 'Classic',   30000,  29479.25, 520.75, 520.75, '2026-12-15');

INSERT INTO loans (loan_no, national_id, loan_type, outstanding_principal, interest_rate, monthly_installment, next_due_date, remaining_months) VALUES
    ('HL6201234567', '3294367792962', 'สินเชื่อบ้าน',      2350000, 5.25, 18500, '2026-12-05', 214),
    ('PL6509876543', '1101700123456', 'สินเชื่อส่วนบุคคล', 85000,   18.0, 4500,  '2026-12-01', 22),
    ('HL5807654321', '3100500678905', 'สินเชื่อบ้าน',      980000,  4.75, 12000, '2026-12-03', 96),
    -- นายสมชาย ใจงาม also has a home loan: with two loans the bot asks which one a request is about.
    ('HL6302228899', '1101700123456', 'สินเชื่อบ้าน',      1680000, 5.5,  14200, '2026-12-05', 180),
    -- PayOff PoC loans (ServiceNow Core Banking mock /loans/PHL-LN-000N)
    ('PHL-LN-0001', '1100800000011', 'สินเชื่อบ้าน', 2450000, 5.25, 18500, '2026-12-05', NULL),
    ('PHL-LN-0002', '1100800000029', 'สินเชื่อบ้าน', 800000,  5.5,  9200,  '2026-12-05', NULL),
    ('PHL-LN-0003', '1100800000037', 'สินเชื่อบ้าน', 1200000, 5.75, 12800, '2026-12-05', NULL),
    ('PHL-LN-0005', '1100800000053', 'สินเชื่อบ้าน', 3900000, 5.1,  27500, '2026-12-05', NULL),
    ('PHL-LN-0006', '1100800000061', 'สินเชื่อบ้าน', 1650000, 5.35, 14200, '2026-12-05', NULL);
-- C4: closed (loan_status "closed" in the mock): nothing left to pay.
INSERT INTO loans (loan_no, national_id, loan_type, outstanding_principal, interest_rate, monthly_installment, next_due_date, remaining_months, status) VALUES
    ('PHL-LN-0004', '1100800000045', 'สินเชื่อบ้าน', 0, 5.4, 0, NULL, 0, 'ปิดแล้ว');

-- A case agents opened earlier, so the bot can answer "เรื่องถึงไหนแล้ว".
INSERT OR IGNORE INTO sn_customerservice_case (sys_id, number, short_description, description, state, priority, category,
                                     contact_type, consumer, opened_at) VALUES
    ('5f1c7a0e9d2b4c6e8a1f3b5d7c9e0a2b', 'CS0001001', 'สอบถามค่าธรรมเนียมรายปีบัตรเครดิต',
     'ลูกค้าขอให้ตรวจสอบค่าธรรมเนียมรายปีบัตร Platinum', 10, 4, 'credit_card', 'phone', '3294367792962',
     '2026-11-20 10:15:00');
