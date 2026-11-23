"""Settings you are likely to change per company. EXAMPLE VALUES for the bank demo:
replace hours, channels and wording with the bank's real ones."""

BRAND = ""          # said in the greeting when set, e.g. "ธนาคารตัวอย่าง"

# The bot's voice. Male: statement and question "ครับ", "ผม". Female: "ค่ะ", "คะ", "ดิฉัน".
STATEMENT_PARTICLE = "ครับ"
QUESTION_PARTICLE = "ครับ"
SELF = "ผม"

# The services, as the greeting reads them out and as the menu buttons.
MAIN_MENU = ["ยอดค้างชำระ", "สินเชื่อและรีไฟแนนซ์", "บัตรเครดิต", "บัญชีเงินฝาก", "แจ้งปัญหาและร้องเรียน"]

HOURS_TEXT = "ทุกวัน 8 โมงเช้าถึง 2 ทุ่ม"
HOTLINE = "02-123-4567"
# Agent hours for the bot to check, Thai time: weekday (0 = Monday) -> (opens, closes) in hours.
# None: agents (or the Genesys queue's own schedule) decide; the bot always hands over.
AGENT_HOURS = None

PAYMENT_CHANNELS = [          # read as one sentence: keep each short
    "แอปธนาคาร",
    "หักบัญชีอัตโนมัติ",
    "เคาน์เตอร์ธนาคารทุกสาขา",
    "เคาน์เตอร์เซอร์วิส 7-Eleven",
]

# Names text-to-speech mispronounces, and how they should sound.
SAY_AS = {
    "7-Eleven": "เซเว่นอีเลฟเว่น",
}

# How many times the bot may misunderstand before it offers a human agent.
MAX_MISUNDERSTOOD = 2

# Identity check: the 13-digit national ID number.
MAX_VERIFY_ATTEMPTS = 3          # per conversation, then hand over
# Per ID number, across conversations: this many failed checks in this many minutes locks that
# number out of the bot's check for a while (an agent can still help).
VERIFY_LOCK_ATTEMPTS = 3
VERIFY_LOCK_MINUTES = 30
MAX_CASE_MISSES = 3              # case numbers not found (or not the customer's) before handing over

# Case states (ServiceNow sn_customerservice_case.state) and how the bot says them to customers.
# The numbers are ServiceNow's usual values: check yours under System Definitions > Choice Lists
# (table sn_customerservice_case, element state) and change them here if they differ.
CASE_STATES = {
    1: "รับเรื่องแล้ว รอดำเนินการ",              # New
    10: "กำลังดำเนินการ",                        # Open
    18: "รอข้อมูลเพิ่มเติมจากคุณลูกค้า",         # Awaiting Info
    6: "แก้ไขแล้ว",                             # Resolved
    3: "ปิดเรื่องแล้ว",                          # Closed
    7: "ยกเลิกแล้ว",                            # Cancelled
}
CASE_STATE_NAMES = {1: "New", 10: "Open", 18: "Awaiting Info", 6: "Resolved", 3: "Closed", 7: "Cancelled"}
CASE_DONE_STATES = (6, 3, 7)
CASE_AWAITING_INFO = 18
