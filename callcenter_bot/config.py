"""Settings you are likely to change per company."""

BRAND = "บริษัท ตัวอย่าง จำกัด"

# The bot's voice. Female: statement "ค่ะ", question "คะ". Male: both "ครับ".
STATEMENT_PARTICLE = "ค่ะ"
QUESTION_PARTICLE = "คะ"
SELF = "ดิฉัน"  # "ผม" for a male voice

HOURS_TEXT = "จันทร์ถึงศุกร์ 8 โมงเช้าถึง 2 ทุ่ม เสาร์อาทิตย์ 9 โมงเช้าถึง 6 โมงเย็น"
# The same hours for the bot to check, Thai time: weekday (0 = Monday) -> (opens, closes) in hours.
# Outside them, a customer who asks for an agent is offered a call back instead.
# Set to None if agents (or the Genesys queue) answer at any time.
AGENT_HOURS = {0: (8, 20), 1: (8, 20), 2: (8, 20), 3: (8, 20), 4: (8, 20), 5: (9, 18), 6: (9, 18)}
HOTLINE = "02-123-4567"

PAYMENT_CHANNELS = [          # read as one sentence: keep each short
    "แอปธนาคารหรือพร้อมเพย์",
    "เคาน์เตอร์เซอร์วิส 7-Eleven",
    "หักบัญชีอัตโนมัติ",
    "บัตรเครดิตบนเว็บไซต์",
]

# Order policies the bot states. EXAMPLES: replace with your real policy.
RETURN_POLICY_TEXT = f"คืนหรือเปลี่ยนสินค้าได้ภายใน 7 วันหลังได้รับสินค้า{STATEMENT_PARTICLE}"
CANCELLABLE_ORDER_STATUSES = ("รอชำระเงิน", "กำลังเตรียมสินค้า")   # later than this: return instead
CALLBACK_PROMISE = "เจ้าหน้าที่จะติดต่อกลับภายใน 24 ชั่วโมง"

# Case states (ServiceNow sn_customerservice_case.state) and how the bot says them to customers.
# The numbers are ServiceNow's usual values: check yours under System Definitions > Choice Lists
# (table sn_customerservice_case, element state) and change them here if they differ.
CASE_STATES = {
    1: "รับเรื่องแล้ว รอเจ้าหน้าที่ดำเนินการ",   # New
    10: "เจ้าหน้าที่กำลังดำเนินการ",             # Open
    18: "รอข้อมูลเพิ่มเติมจากลูกค้า",            # Awaiting Info
    6: "แก้ไขแล้ว",                             # Resolved
    3: "ปิดเรื่องแล้ว",                          # Closed
    7: "ยกเลิกแล้ว",                            # Cancelled
}
CASE_STATE_NAMES = {1: "New", 10: "Open", 18: "Awaiting Info", 6: "Resolved", 3: "Closed", 7: "Cancelled"}
CASE_DONE_STATES = (6, 3, 7)
CASE_AWAITING_INFO = 18

# Names text-to-speech mispronounces, and how they should sound.
SAY_AS = {
    "7-Eleven": "เซเว่นอีเลฟเว่น",
    "Kerry Express": "เคอรี่ เอ็กซ์เพรส",
    "QR": "คิวอาร์",
}

MAIN_MENU = ["เช็คยอดค้างชำระ", "ติดตามคำสั่งซื้อ", "แจ้งปัญหา", "คุยกับเจ้าหน้าที่"]

# How many times the bot may misunderstand before it offers a human agent.
MAX_MISUNDERSTOOD = 2
MAX_VERIFY_ATTEMPTS = 3
