"""Clean up what the customer typed before any rule looks at it.

Thai has no spaces between words and customers type casually, so the rules match against
a "compact" form: Thai digits turned into 0-9, stretched letters shortened ("ครับบบบ"),
polite particles at the end removed, and spaces taken out.
"""
import re
import unicodedata

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
ZERO_WIDTH = re.compile("[​‌‍﻿]")
# A letter typed three or more times in a row ("มากกกก", "ครับบบ") counts once.
STRETCHED = re.compile(r"(\D)\1{2,}")  # never digits: 0811112222 is a real number
# Laughter: 555, ๕๕๕, 5555+
LAUGH = re.compile(r"(?<!\d)5{3,}(?!\d)")
# Polite particles that change nothing about what is asked.
PARTICLES = (
    "ครับผม", "ครับ", "คับ", "ค่ะ", "คะ", "ค่า", "จ้า", "จ้ะ", "จ๊ะ", "ฮะ", "งับ", "นะคะ", "นะครับ", "นะ",
)
# Words that end like a particle keep their ending: ระงับ is not ระ + งับ, บังคับ is not บัง + คับ.
NOT_PARTICLE_AFTER = {"งับ": "ระ", "คับ": "บัง"}
TRAILING_PARTICLES = re.compile(
    "(?:" + "|".join((f"(?<!{NOT_PARTICLE_AFTER[p]})" if p in NOT_PARTICLE_AFTER else "") + re.escape(p)
                     for p in sorted(PARTICLES, key=len, reverse=True)) + r")+\s*[.!?~]*$"
)


def normalize(text: str) -> str:
    """Readable cleaned text: same words, standard digits, tidy spacing."""
    text = unicodedata.normalize("NFC", text or "")
    text = ZERO_WIDTH.sub("", text).translate(THAI_DIGITS).lower()
    text = LAUGH.sub(" ", text)
    text = STRETCHED.sub(r"\1", text)
    text = text.replace("แอพ", "แอป")   # both spellings are common; keywords use แอป
    return re.sub(r"\s+", " ", text).strip()


def strip_particles(text: str) -> str:
    """Remove polite particles at the end: "ยกเลิกครับ" -> "ยกเลิก"."""
    return TRAILING_PARTICLES.sub("", text).strip()


def compact(text: str) -> str:
    """Form used for Thai keyword matching: no spaces, no trailing particles."""
    return re.sub(r"[\s\-_.,!?~]+", "", strip_particles(normalize(text)))


# Digits said aloud, as speech recognition sometimes writes them: "ศูนย์แปดหนึ่ง..." -> "081...".
DIGIT_WORDS = {
    "ศูนย์": "0", "หนึ่ง": "1", "เอ็ด": "1", "สอง": "2", "สาม": "3", "สี่": "4",
    "ห้า": "5", "หก": "6", "เจ็ด": "7", "แปด": "8", "เก้า": "9",
}
_DIGIT_TOKEN = "(?:" + "|".join(DIGIT_WORDS) + r"|\d)"
# Only runs of 4 or more, so ordinary words ("หกล้ม", "สามคน") are left alone.
SPOKEN_NUMBER = re.compile(_DIGIT_TOKEN + r"(?:[\s\-]*" + _DIGIT_TOKEN + "){3,}")
_ONE_TOKEN = re.compile(_DIGIT_TOKEN)


def spoken_digits(text: str) -> str:
    """"ศูนย์ แปด หนึ่ง สอง" -> "0812"."""
    return SPOKEN_NUMBER.sub(
        lambda m: "".join(DIGIT_WORDS.get(t, t) for t in _ONE_TOKEN.findall(m.group())), text)


def digits_only(text: str) -> str:
    """Join digits that customers split with spaces or dashes, or said as words:
    "081-234 5678" -> "0812345678"."""
    return re.sub(r"(?<=\d)[\s\-]+(?=\d)", "", spoken_digits(normalize(text)))


def e164(phone: str) -> str:
    """"0810000002" -> "+66810000002" (how ServiceNow and Genesys write Thai numbers)."""
    return "+66" + phone[1:] if phone and phone.startswith("0") else (phone or "")


def phone_from_ani(ani) -> str:
    """The caller's number as Genesys gives it ("tel:+66815493626", "+66 81 549 3626") as a Thai
    phone number ("0815493626"). Empty when there is none."""
    digits = re.sub(r"\D", "", str(ani or ""))
    if digits.startswith("66") and len(digits) in (10, 11):
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"0\d{8,9}", digits) else ""
