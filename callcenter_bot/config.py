"""Settings you are likely to change per company."""

BRAND = "บริษัท ตัวอย่าง จำกัด"

# The bot's voice. Female: statement "ค่ะ", question "คะ". Male: both "ครับ".
STATEMENT_PARTICLE = "ค่ะ"
QUESTION_PARTICLE = "คะ"
SELF = "ดิฉัน"  # "ผม" for a male voice

HOURS_TEXT = "จันทร์ถึงศุกร์ 8 โมงเช้าถึง 2 ทุ่ม เสาร์อาทิตย์ 9 โมงเช้าถึง 6 โมงเย็น"
HOTLINE = "02-123-4567"

PAYMENT_CHANNELS = [          # read as one sentence: keep each short
    "แอปธนาคารหรือพร้อมเพย์",
    "เคาน์เตอร์เซอร์วิส 7-Eleven",
    "หักบัญชีอัตโนมัติ",
    "บัตรเครดิตบนเว็บไซต์",
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
