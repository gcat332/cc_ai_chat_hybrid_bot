"""Which topic a message is about, by keyword rules.

To add or tune a topic, edit KEYWORDS only. Thai keywords match anywhere inside the message
(Thai has no spaces). English keywords match as whole words, so "hi" does not match "this".
Longer keyword matches count more, so "ยกเลิกคำสั่งซื้อ" beats a bare "คำสั่งซื้อ".
"""
import re

from .normalize import compact, normalize

KEYWORDS = {
    "greeting": ["สวัสดี", "หวัดดี", "ดีจ้า", "hello", "hi", "hey"],
    "check_balance": [
        "ยอดค้าง", "ค้างชำระ", "ค้างจ่าย", "ยอดชำระ", "ยอดบิล", "เช็คยอด", "เช็กยอด", "ดูยอด",
        "ยอดที่ต้องจ่าย", "ต้องจ่ายเท่า", "ต้องชำระเท่า", "บิล", "ใบแจ้งหนี้", "ค่าบริการ",
        "ครบกำหนด", "balance", "bill",
    ],
    "payment_channels": [
        "ช่องทางชำระ", "ช่องทางการชำระ", "ช่องทางจ่าย", "จ่ายยังไง", "จ่ายได้ที่ไหน", "จ่ายที่ไหน",
        "ชำระยังไง", "ชำระได้ที่ไหน", "ชำระที่ไหน", "จ่ายผ่าน", "ชำระผ่าน", "พร้อมเพย์",
        "promptpay", "โอนเข้าบัญชี", "เลขบัญชี", "ตัดบัตร",
    ],
    "order_status": [
        "คำสั่งซื้อ", "ออเดอร์", "ออร์เดอร์", "พัสดุ", "ของยังไม่มา", "ของยังไม่ได้", "ของจะมา",
        "ติดตามสินค้า", "ติดตามการจัดส่ง", "เลขพัสดุ", "จัดส่ง", "ส่งของ", "สินค้าถึง",
        "order", "tracking", "delivery",
    ],
    "report_problem": [
        "แจ้งปัญหา", "มีปัญหา", "ใช้งานไม่ได้", "ใช้ไม่ได้", "ไม่ทำงาน", "ขัดข้อง", "เสีย",
        "เน็ตหลุด", "เน็ตช้า", "เน็ตใช้ไม่ได้", "ร้องเรียน", "ไม่พอใจ", "แจ้งซ่อม",
        "complaint", "problem", "error",
    ],
    "agent": [
        "เจ้าหน้าที่", "พนักงาน", "คุยกับคน", "ขอสายคน", "ต่อสาย", "โอเปอเรเตอร์", "แอดมิน",
        "agent", "human", "operator", "admin",
    ],
    "hours": [
        "เวลาทำการ", "เวลาเปิด", "เปิดกี่โมง", "ปิดกี่โมง", "เปิดวันไหน", "เปิดทุกวัน",
        "วันหยุด", "opening hours", "office hours",
    ],
    "thanks": ["ขอบคุณ", "ขอบใจ", "แต๊งกิ้ว", "thank", "thanks", "thx"],
    "goodbye": [
        "ลาก่อน", "บ๊ายบาย", "บายบาย", "แค่นี้ก่อน", "แค่นี้แหละ", "ไม่มีอะไรแล้ว", "ไม่มีแล้ว", "จบการสนทนา", "จบแชท",
        "bye", "goodbye",
    ],
}

# Said on its own, these leave the current step; inside a longer line they mean something
# else ("ยกเลิกคำสั่งซื้อ" is a request about an order, not "stop").
CANCEL_WORDS = {"ยกเลิก", "ไม่เอาแล้ว", "เปลี่ยนใจ", "ช่างมัน", "ไม่ต้องแล้ว", "cancel", "stop"}
YES_WORDS = {"ใช่", "ถูกต้อง", "ถูก", "ได้", "โอเค", "ตกลง", "ok", "okay", "yes", "y"}
NO_WORDS = {"ไม่", "ไม่ใช่", "ไม่ถูก", "ผิด", "no", "n"}
# Checked before YES_PREFIXES: "ไม่ใช่..." must not count as "ใช่".
NO_PREFIXES = ("ไม่ใช่", "ไม่ถูก", "ผิด")  # Thai only: "nothing" starts with "no"
YES_PREFIXES = ("ใช่", "ถูกต้อง", "โอเค", "ตกลง")


def _matches(keyword: str, text: str, compact_text: str) -> bool:
    if keyword.isascii():
        return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None
    return keyword in compact_text


def detect(message: str):
    """Return (intent, score) for the best matching topic, or (None, 0)."""
    text, compact_text = normalize(message), compact(message)
    best, best_score = None, 0
    for intent, keywords in KEYWORDS.items():
        score = sum(len(k) for k in keywords if _matches(k, text, compact_text))
        if score > best_score:
            best, best_score = intent, score
    return best, best_score


def is_cancel(message: str) -> bool:
    return compact(message) in CANCEL_WORDS


def yes_no(message: str):
    """True for yes, False for no, None when the line is neither.
    Spoken answers run on ("ใช่ครับถูกต้อง"), so a line that starts with a clear yes or no counts."""
    c = compact(message)
    if c in NO_WORDS or c.startswith(NO_PREFIXES):
        return False
    if c in YES_WORDS or c.startswith(YES_PREFIXES):
        return True
    return None
