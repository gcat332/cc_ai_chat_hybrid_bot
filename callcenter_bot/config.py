"""Settings you are likely to change per company."""

BRAND = "บริษัท ตัวอย่าง จำกัด"

# The bot's voice. Female: statement "ค่ะ", question "คะ". Male: both "ครับ".
STATEMENT_PARTICLE = "ค่ะ"
QUESTION_PARTICLE = "คะ"
SELF = "ดิฉัน"  # "ผม" for a male voice

HOURS_TEXT = "จันทร์ถึงศุกร์ 08:00–20:00 น. และเสาร์–อาทิตย์ 09:00–18:00 น."
HOTLINE = "02-123-4567"

PAYMENT_CHANNELS = [
    "แอปธนาคารผ่านพร้อมเพย์ หรือสแกน QR บนใบแจ้งหนี้",
    "เคาน์เตอร์เซอร์วิส 7-Eleven",
    "หักบัญชีธนาคารอัตโนมัติ",
    "บัตรเครดิตผ่านเว็บไซต์",
]

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
