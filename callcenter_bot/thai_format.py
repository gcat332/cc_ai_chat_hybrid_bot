"""Thai formatting for dates, money and masked numbers."""

MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def thai_date(d) -> str:
    """date(2026, 12, 5) -> "5 ธันวาคม 2569" (Buddhist year)."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year + 543}"


def baht(amount: float) -> str:
    return f"{amount:,.2f} บาท"


def mask_phone(phone: str) -> str:
    """"0812345678" -> "081-xxx-5678", safe to show and log."""
    return f"{phone[:3]}-xxx-{phone[-4:]}" if phone and len(phone) >= 7 else "xxx"


# ---- Text to speech: say numbers the way a Thai call-center agent would ------------------------
# The screen shows the text as written; text-to-speech gets this version, with the same words.
import re as _re

_DIGIT = "ศูนย์ หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า".split()
_LETTER = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                   ("เอ บี ซี ดี อี เอฟ จี เอช ไอ เจ เค แอล เอ็ม เอ็น โอ พี คิว อาร์ เอส ที ยู วี "
                    "ดับเบิลยู เอ็กซ์ วาย แซด").split()))


def _spell(code: str) -> str:
    """"0812345678" -> "ศูนย์ แปด หนึ่ง ..." and "TK1001" -> "ที เค หนึ่ง ศูนย์ ศูนย์ หนึ่ง"."""
    return " ".join(_DIGIT[int(ch)] if ch.isdigit() else _LETTER.get(ch.upper(), "")
                    for ch in code if ch.isalnum())


def _time(m) -> str:
    hour, minute = int(m.group(1)), int(m.group(2))
    return f"{hour} นาฬิกา" + (f" {minute} นาที" if minute else "")


def _money(m) -> str:
    baht_part, satang = m.group(1).replace(",", ""), int(m.group(2) or 0)
    return f"{baht_part} บาท" + (f" {satang} สตางค์" if satang else "")


def speech_text(text: str, say_as=None) -> str:
    """Rewrite a reply so text-to-speech reads it as written. `say_as` maps names that
    TTS mispronounces to how they should sound, e.g. {"7-Eleven": "เซเว่นอีเลฟเว่น"}."""
    for written, spoken in (say_as or {}).items():
        text = text.replace(written, spoken)
    text = _re.sub(r"\b\d{3}-x{3}-(\d{4})\b", lambda m: "ที่ลงท้ายด้วย " + _spell(m.group(1)), text)  # masked phone
    text = _re.sub(r"^\s*(\d+)\.\s+", r"ข้อ \1 ", text, flags=_re.M)            # "1. ..." list items
    text = _re.sub(r"(\d{1,2}):(\d{2})\s*(?:น\.)?", _time, text)                 # 08:00 น.
    text = _re.sub(r"(\d[\d,]*)(?:\.(\d{2}))?\s*บาท", _money, text)              # 1,250.50 บาท
    # Codes said one character at a time: phone/order/ticket/tracking numbers.
    text = _re.sub(r"\b[A-Za-z]{1,4}\d{3,}[A-Za-z]{0,3}\b", lambda m: _spell(m.group()), text)
    text = _re.sub(r"(?<![\d,.])\d(?:[\d\-]*\d){4,}(?![\d,.])", lambda m: _spell(m.group()), text)
    text = text.replace("–", " ถึง ")
    text = _re.sub(r"[()\"“”]", " ", text)
    return _re.sub(r"\s+", " ", text).strip()
