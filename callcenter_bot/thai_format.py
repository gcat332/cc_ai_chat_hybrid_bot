"""Thai formatting for dates, money and masked numbers."""

MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def thai_date(d, today=None) -> str:
    """date(2026, 12, 5) -> "5 ธันวาคม 2569" (Buddhist year). Within about six months of today the
    year is left out, as people say it: "5 ธันวาคม"."""
    from datetime import date
    today = today or date.today()
    if abs((d - today).days) <= 180:
        return f"{d.day} {MONTHS[d.month - 1]}"
    return f"{d.day} {MONTHS[d.month - 1]} {d.year + 543}"


def baht(amount: float) -> str:
    """37550 -> "37,550 บาท", 85420.5 -> "85,420.50 บาท": no ".00" on whole amounts."""
    return f"{amount:,.0f} บาท" if float(amount).is_integer() else f"{amount:,.2f} บาท"


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


_NBSP = "\u00a0"   # holds words together while pauses are added; becomes a plain space at the end
_THAI = "\u0e00-\u0e7f"


def _spell(code: str, groups=None) -> str:
    """"0812345678" -> "ศูนย์ แปด หนึ่ง, สอง สาม สี่, ห้า หก เจ็ด แปด": one character at a time,
    with a short pause between groups the way an agent reads a number back."""
    parts = _re.split(r"[\s\-]+", code) if _re.search(r"[\s\-]", code) else None
    if parts is None:
        letters = _re.match(r"[A-Za-z]*", code).group()
        digits = code[len(letters):]
        if len(digits) == 10:
            sizes = (3, 3, 4)
        elif len(digits) == 9:
            sizes = (2, 3, 4)
        elif len(digits) > 4:
            sizes = (3,) * (len(digits) // 3) + ((len(digits) % 3,) if len(digits) % 3 else ())
        else:
            sizes = (len(digits),)
        parts, i = ([letters] if letters else []), 0
        for n in sizes:
            parts.append(digits[i:i + n])
            i += n
    words = [" ".join(_DIGIT[int(ch)] if ch.isdigit() else _LETTER.get(ch.upper(), "")
                      for ch in part if ch.isalnum()) for part in parts if part]
    return ", ".join(w for w in words if w)


def _time(m) -> str:
    hour, minute = int(m.group(1)), int(m.group(2))
    return f"{hour} นาฬิกา" + (f" {minute} นาที" if minute else "")


def _money(m) -> str:
    baht_part, satang = m.group(1).replace(",", ""), int(m.group(2) or 0)
    return f"{baht_part} บาท" + (f" {satang} สตางค์" if satang else "")


def speech_text(text: str, say_as=None, keep_together=()) -> str:
    """Rewrite a reply so text-to-speech reads it as written, with pauses where an agent would
    pause. `say_as` maps names TTS mispronounces to how they should sound, e.g.
    {"7-Eleven": "เซเว่นอีเลฟเว่น"}. `keep_together` lists names never to pause inside,
    e.g. the company name.

    Pauses: "." after a sentence (after ค่ะ/คะ/ครับ), "," between phrases (where Thai text has a
    space), and "," between the groups of a phone, order or ticket number."""
    for written, spoken in (say_as or {}).items():   # a name inside a phrase: no pause around it
        text = _re.sub(f" ?{_re.escape(written)}", lambda m: m.group().replace(written, spoken)
                       .replace(" ", _NBSP), text)
    for phrase in keep_together:
        text = text.replace(phrase, phrase.replace(" ", _NBSP))
    text = _re.sub(r"\b\d{3}-x{3}-(\d{4})\b", "ที่ลงท้ายด้วย ⟦\\1⟧", text)            # masked phone
    text = _re.sub(r"(ลงท้าย(?:ด้วย)?)\s*(\d{3,6})\b", "\\1 ⟦\\2⟧", text)              # card/account ends 7788
    text = _re.sub(r"^\s*(\d+)\.\s+", r"ข้อ \1 ", text, flags=_re.M)                # "1. ..." list items
    text = _re.sub(r"(\d{1,2}):(\d{2})\s*(?:น\.)?", _time, text)                     # 08:00 น.
    text = _re.sub(r"(\d[\d,]*)(?:\.(\d{2}))?\s*บาท", _money, text)                  # 1,250.50 บาท
    text = text.replace("–", f"{_NBSP}ถึง{_NBSP}")
    text = _re.sub(r"[()\"“”]", " ", text)
    text = _re.sub(r"[ \t]+", " ", text).strip()
    # Pauses, before numbers are spelled out (so the digit words are not split up).
    text = _re.sub(f"(ค่ะ|คะ|ครับ|จ้ะ|จ้า)\\s*\\n\\s*|(ค่ะ|คะ|ครับ|จ้ะ|จ้า)[ {_NBSP}]",
                   lambda m: (m.group(1) or m.group(2)) + ". ", text)
    text = _re.sub(r"\s*\n\s*", ". ", text)
    text = _re.sub(f"(?<=[{_THAI}]) (?=[{_THAI}])(?!(?:ค่ะ|คะ|ครับ|จ้ะ|จ้า)(?:[.,\\s]|$))", ", ", text)
    # Codes said one character at a time: phone/order/ticket/tracking numbers.
    # ⟪ marks the end of a spelled number: a pause there when the sentence goes on in Thai.
    text = _re.sub(r"⟦(\d+)⟧", lambda m: " ".join(_DIGIT[int(c)] for c in m.group(1)) + "⟪", text)
    text = _re.sub(r"\b[A-Za-z]{1,4}\d{3,}[A-Za-z]{0,3}\b", lambda m: _spell(m.group()) + "⟪", text)
    # ...but not an amount of money: "37550 บาท" is read as a number.
    text = _re.sub(r"(?<![\d,.])\d(?:[\d\-]*\d){4,}(?![\d,.])(?!\s*บาท)", lambda m: _spell(m.group()) + "⟪", text)
    text = _re.sub(f"⟪ (?=[{_THAI}])(?!(?:ค่ะ|คะ|ครับ|จ้ะ|จ้า)(?:[.\\s]|$))", ", ", text).replace("⟪", "")
    text = text.replace(_NBSP, " ")
    return _re.sub(r"\s+", " ", text).strip()
