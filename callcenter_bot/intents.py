"""Which topic a message is about, by keyword rules.

To add or tune a topic, edit KEYWORDS only. Thai keywords match anywhere inside the message
(Thai has no spaces). English keywords match as whole words, so "hi" does not match "this".
Longer keyword matches count more, so "ปิดบัญชีสินเชื่อบ้าน" beats a bare "สินเชื่อบ้าน".
"""
import re

from .normalize import compact, normalize

KEYWORDS = {
    "greeting": ["สวัสดี", "หวัดดี", "ดีจ้า", "ฮัลโหล", "ฮาโหล", "ฮัลโล", "hello", "hi", "hey"],
    # ---- inquiries: the bot answers them itself, after the identity check ----
    "balance_due": [
        "ยอดค้างชำระ", "ค้างชำระ", "ยอดชำระขั้นต่ำ", "ชำระขั้นต่ำ", "ขั้นต่ำ", "ยอดที่ต้องชำระ",
        "ต้องจ่ายเท่า", "ต้องชำระเท่า", "วันครบกำหนด", "ครบกำหนด", "กำหนดชำระ", "ค่างวด", "ยอดบัตรเครดิต", "ยอดบัตร",
        "ยอดค้าง", "ยอดคลัง",  # speech-to-text often hears ค้าง as คลัง
        "ต้องโอนเท่า", "ต้องจ่ายบัตร", "บิลเดือนนี้", "ยอดบิล", "ค้างจ่าย", "จ่ายวันไหน", "ชำระวันไหน", "งวดนี้",
        "ค่าบ้านเดือนนี้", "ยอดที่ต้องจ่าย", "หนี้บัตร",
    ],
    "loan_info": [
        "ข้อมูลสินเชื่อ", "สินเชื่อบ้าน", "สินเชื่อส่วนบุคคล", "ยอดหนี้", "หนี้คงเหลือ", "ดอกเบี้ยบ้าน",
        "อัตราดอกเบี้ย", "ผ่อนอีกกี่งวด", "งวดที่เหลือ", "สินเชื่อ", "หนี้บ้าน", "ผ่อนบ้านเหลือ",
        "เหลืออีกกี่งวด", "กู้บ้าน", "เงินต้นคงเหลือ",
    ],
    "card_info": ["บัตรเครดิต", "วงเงินคงเหลือ", "วงเงินบัตร", "วงเงินเหลือ", "ยอดใช้จ่ายบัตร", "เครดิตเหลือ"],
    "deposit_balance": [
        "ยอดเงินในบัญชี", "เงินในบัญชี", "ยอดเงินคงเหลือ", "ยอดในบัญชี", "บัญชีออมทรัพย์", "บัญชีเงินฝาก",
        "เงินฝาก", "เช็คยอดเงิน", "ดูยอดเงิน", "ยอดเงินออม", "บัญชีมีเงิน", "เท่าไหร่ในบัญชี", "เท่าไรในบัญชี",
    ],
    "case_status": [
        "เช็คเรื่อง", "เช็กเรื่อง", "ติดตามเรื่อง", "ตามเรื่อง", "สถานะเรื่อง", "เรื่องที่แจ้ง",
        "เรื่องถึงไหน", "เลขที่เรื่อง", "เรื่องร้องเรียนถึงไหน", "ติดตามเคส", "สถานะเคส", "เช็คเคส", "เช็กเคส",
        "เลขเคส", "ไม่มีใครติดต่อกลับ", "ยังไม่ติดต่อกลับ",
    ],
    "payment_channels": [
        "ช่องทางชำระ", "ช่องทางการชำระ", "จ่ายยังไง", "ชำระยังไง", "จ่ายที่ไหน", "ชำระที่ไหน",
        "จ่ายได้ที่ไหน", "ชำระได้ที่ไหน", "จ่ายผ่าน", "ชำระผ่าน", "ช่องทางไหน", "จ่ายบัตร", "ชำระบัตร",
        "จ่ายบิล", "ชำระบิล", "ชำระค่างวดได้", "จ่ายค่างวดได้",
    ],
    # ---- requests: they open work, so an agent handles them (after the identity check) ----
    "loan_close": [
        "ปิดบัญชีสินเชื่อบ้าน", "ปิดบัญชีสินเชื่อ", "ปิดสินเชื่อบ้าน", "ปิดสินเชื่อ", "ปิดบัญชีบ้าน",
        "ปิดยอดบ้าน", "ไถ่ถอน", "รีไฟแนนซ์บ้าน", "รีไฟแนนซ์", "รีไฟแนนท์", "ย้ายสินเชื่อ",
        "ย้ายไปธนาคาร", "ย้ายธนาคาร", "โปะหมด", "ปิดหนี้", "refinance", "ยอดปิดบัญชี", "ยอดปิดสินเชื่อ", "ยอดไถ่ถอน",
        "ปิดยอดสินเชื่อบ้าน", "ปิดยอดสินเชื่อ", "ปิดสินเชื่อก่อนกำหนด", "ปิดบ้านก่อนกำหนด", "payoff",
        "ปิดบ้าน", "ปิดหนี้บ้าน",
    ],
    # Loan customers who may leave: the retention team's chance, so an agent takes them.
    "loan_rate_review": ["ลดดอกเบี้ย", "ขอลดดอก", "ลดดอก", "ดอกเบี้ยแพง", "ดอกแพง", "ดอกเบี้ยสูง", "ปรับดอกเบี้ย",
                         "ขอดอกเบี้ยใหม่", "ดอกเบี้ยถูกกว่า", "ดอกถูกกว่า"],
    "loan_restructure": ["ผ่อนไม่ไหว", "ค่างวดสูง", "ขอลดค่างวด", "ลดค่างวด", "พักชำระ", "พักหนี้", "ปรับโครงสร้างหนี้",
                         "ขยายเวลาผ่อน", "ยืดเวลาผ่อน", "จ่ายไม่ไหว", "ตกงาน", "จ่ายไม่ทัน", "ขอเลื่อนจ่าย", "ขอเลื่อนงวด"],
    "deposit_close": ["ปิดบัญชีเงินฝาก", "ปิดบัญชีเงิน", "ปิดบัญชีออมทรัพย์", "ปิดบัญชีออม", "ปิดบัญชีฝาก",
                      "ปิดบัญชีฝากประจำ", "ปิดบัญชีธนาคาร"],
    "card_apply": ["สมัครบัตรเครดิต", "สมัครบัตร", "ทำบัตรใหม่", "ขอบัตรเครดิต", "อยากได้บัตร", "ทำบัตรเครดิต"],
    "card_limit": ["เพิ่มวงเงินบัตรเครดิต", "เพิ่มวงเงิน", "ขยายวงเงิน", "ขอวงเงินเพิ่ม", "ปรับวงเงิน"],
    "card_cancel": ["ยกเลิกบัตรเครดิต", "ยกเลิกบัตร", "ปิดบัตรเครดิต", "ปิดบัตร", "เลิกใช้บัตร", "ไม่อยากใช้บัตร"],
    "transaction_help": ["โอนเงิน", "ฝากเงิน", "ถอนเงิน", "โอนไม่ได้", "โอนผิด", "โอนเงินผิดบัญชี", "โอนไม่เข้า", "เงินไม่เข้า",
                         "ปลายทางไม่ได้รับ", "ปลายทางยังไม่ได้รับ"],
    "complaint": [
        "ร้องเรียน", "แจ้งปัญหา", "มีปัญหา", "ใช้งานไม่ได้", "ใช้ไม่ได้", "เข้าแอปไม่ได้",
        "แอปเข้าไม่ได้", "ไม่พอใจ", "บริการแย่", "complaint", "เด้งออก", "แอปเด้ง", "ระบบล่ม", "แอปล่ม",
    ],
    # ---- urgent: no confirmation question, straight to verification and an agent ----
    "card_lost": ["บัตรเครดิตหาย", "บัตรเครดิตถูกขโมย", "บัตรหาย", "ทำบัตรหาย", "บัตรถูกขโมย", "อายัดบัตร", "ระงับบัตร",
                  "กระเป๋าหาย", "กระเป๋าตังค์หาย", "กระเป๋าตังหาย", "กระเป๋าเงินหาย", "ขโมยกระเป๋า", "กระเป๋าโดนขโมย",
                  "กระเป๋าถูกขโมย"],
    "unauthorized": [
        "รายการที่ไม่ได้ทำ", "ไม่ได้ทำรายการ", "ไม่ได้ใช้จ่าย", "รายการผิดปกติ", "ถูกหักเงิน",
        "เงินหาย", "ยอดเงินหาย", "มิจฉาชีพ", "โดนหลอก", "ถูกหลอก", "โดนแฮก", "ถูกแฮก", "โดนแฮ็ก", "ถูกแฮ็ก",
        "เอาบัตรไปใช้", "โดนตัดเงิน", "ถูกตัดเงิน", "แก๊งคอลเซ็นเตอร์", "หลอกโอน", "สวมรอย",
    ],
    "agent": [
        "เจ้าหน้าที่", "พนักงาน", "คุยกับคน", "ขอสายคน", "ต่อสาย", "โอนสาย", "โอเปอเรเตอร์",
        "คนจริง", "บอทไม่รู้เรื่อง", "ไม่อยากคุยกับบอท", "ไม่คุยกับบอท", "agent", "human", "operator",
    ],
    "hours": [
        "เวลาทำการ", "เวลาเปิด", "เปิดกี่โมง", "ปิดกี่โมง", "เปิดวันไหน", "เปิดทุกวัน",
        "มีเจ้าหน้าที่ไหม", "เจ้าหน้าที่อยู่ไหม", "ถึงกี่โมง", "opening hours", "office hours",
    ],
    "thanks": ["ขอบคุณ", "ขอบใจ", "แต๊งกิ้ว", "thank", "thanks", "thx"],
    "goodbye": [
        "ลาก่อน", "บ๊ายบาย", "บายบาย", "แค่นี้ก่อน", "แค่นี้แหละ", "ไม่มีอะไรแล้ว", "ไม่มีแล้ว",
        "จบการสนทนา", "จบแชท", "bye", "goodbye",
    ],
}

# Said on its own, these leave the current step; inside a longer line they mean something
# else ("ยกเลิกบัตร" is a request about a card, not "stop").
CANCEL_WORDS = {"ยกเลิก", "ไม่เอาแล้ว", "เปลี่ยนใจ", "ช่างมัน", "ไม่ต้องแล้ว", "cancel", "stop"}
YES_WORDS = {"ใช่", "ถูกต้อง", "ถูก", "ได้", "โอเค", "ตกลง", "ok", "okay", "yes", "y"}
NO_WORDS = {"ไม่", "ไม่ใช่", "ไม่ถูก", "ผิด", "no", "n"}
# Checked before YES_PREFIXES: "ไม่ใช่..." must not count as "ใช่".
NO_PREFIXES = ("ไม่ใช่", "ไม่ถูก", "ผิด", "ไม่ต้อง", "ไม่เอา", "ไม่มี")  # Thai only: "nothing" starts with "no"
YES_PREFIXES = ("ใช่", "ถูกต้อง", "โอเค", "ตกลง")


def _matches(keyword: str, text: str, compact_text: str) -> bool:
    if keyword.isascii():
        return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None
    if keyword.startswith("ปิด"):     # "เปิดบัญชี" (open) contains "ปิดบัญชี" (close)
        return re.search("(?<!เ)" + re.escape(keyword), compact_text) is not None
    return keyword in compact_text


def keyword_score(keywords, message: str) -> int:
    """How strongly `message` matches `keywords`: the length of every keyword found, added up."""
    text, compact_text = normalize(message), compact(message)
    return sum(len(k) for k in keywords if _matches(k, text, compact_text))


def detect(message: str):
    """Return (intent, score) for the best matching topic, or (None, 0)."""
    best, best_score = None, 0
    for intent, keywords in KEYWORDS.items():
        score = keyword_score(keywords, message)
        if score > best_score:
            best, best_score = intent, score
    return best, best_score


# Sounds people make while thinking, and speech recognition's half-heard words. A line made only of
# these is not a request: the bot waits for the rest instead of saying it did not understand.
POLITE = ("ครับผม", "ครับ", "คับ", "ค่ะ", "คะ", "ค่า", "จ้ะ", "จ้า")
FILLERS = POLITE + ("ฮัลโหล", "ฮาโหล", "แบบว่า", "อันนี้", "เอ่อ", "เออ", "เอ้อ", "อ่า", "อ่ะ", "อะ", "อืม", "อือ",
                    "อ๋อ", "อ้อ", "อ่อ", "อ้าว", "นี่", "คือ", "นะ", "ก็")


def _without(words, message: str) -> str:
    text = re.sub(r"[\s\-_.,!?~]+", "", normalize(message))
    for word in sorted(words, key=len, reverse=True):
        text = text.replace(word, "")
    return text


def _only(words, message: str) -> bool:
    return not _without(words, message)


def is_fragment(message: str) -> bool:
    """"ครับ ลูก": a filler and a scrap of a word. On the phone this is speech recognition closing the
    turn too early (the caller paused, or started talking over the greeting), not a request."""
    rest = _without(FILLERS, message)
    return (0 < len(rest) <= 3 and rest != re.sub(r"\s+", "", normalize(message))
            and rest not in YES_WORDS | NO_WORDS)


def is_filler(message: str) -> bool:
    """"เอ่อ", "อ๋อ ครับ", "ฮัลโหล": nothing asked yet."""
    return bool(normalize(message)) and _only(FILLERS, message)


def is_polite_only(message: str) -> bool:
    """"ครับ" / "ค่ะ" on their own: after a yes/no question, that is a yes."""
    return bool(normalize(message)) and _only(POLITE, message)


def is_cancel(message: str) -> bool:
    return compact(message) in CANCEL_WORDS


def yes_no(message: str):
    """True for yes, False for no, None when the line is neither.
    Spoken answers run on ("ใช่ครับถูกต้อง"), so a line that starts with a clear yes or no counts;
    sounds before it ("ครับ ใช่", "เอ่อ ไม่ใช่") are skipped."""
    answer = _yes_no(compact(message))
    if answer is None and re.match(r"\s*(?:" + "|".join(FILLERS) + ")", normalize(message)):
        answer = _yes_no(_without(FILLERS, message))
    return answer


def _yes_no(c: str):
    if c in NO_WORDS or c.startswith(NO_PREFIXES):
        return False
    if c in YES_WORDS or c.startswith(YES_PREFIXES):
        return True
    return None
