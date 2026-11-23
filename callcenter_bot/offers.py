"""What a customer says about the other bank's offer and how soon they must close a loan, as
numbers for the agent and ServiceNow (participant data: new_interest_rate, cashback_offered,
promotion_period_months, closing_within_days, new_bank_name).

Speech recognition writes numbers as digits ("3.25 เปอร์เซ็นต์") or as words ("สามจุดสองห้า
เปอร์เซ็นต์", "ห้าพันบาท"): both are read. Only numbers next to a unit are taken.
"""
import calendar
import re
from datetime import date
from typing import Optional

from .normalize import normalize

DIGITS = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6,
          "เจ็ด": 7, "แปด": 8, "เก้า": 9}
UNITS = {"สิบ": 10, "ร้อย": 100, "พัน": 1000, "หมื่น": 10000, "แสน": 100000, "ล้าน": 1000000}
_WORD = "|".join(sorted(list(DIGITS) + list(UNITS) + ["จุด"], key=len, reverse=True))
NUMBER_WORDS = re.compile(f"(?:{_WORD})+")
TOKEN = re.compile(_WORD)

# Banks customers move to, as said -> as written for the agent.
BANKS = {"กสิกร": "กสิกรไทย", "kbank": "กสิกรไทย", "ไทยพาณิชย์": "ไทยพาณิชย์", "scb": "ไทยพาณิชย์",
         "กรุงศรี": "กรุงศรีอยุธยา", "กรุงไทย": "กรุงไทย", "ktb": "กรุงไทย", "กรุงเทพ": "กรุงเทพ", "bbl": "กรุงเทพ",
         "ทีทีบี": "ทีทีบี", "ttb": "ทีทีบี", "ทหารไทย": "ทีทีบี", "ออมสิน": "ออมสิน", "ธอส": "ธอส.",
         "อาคารสงเคราะห์": "ธอส.", "ยูโอบี": "ยูโอบี", "uob": "ยูโอบี", "ซีไอเอ็มบี": "ซีไอเอ็มบี", "cimb": "ซีไอเอ็มบี",
         "แลนด์แอนด์เฮ้าส์": "แลนด์ แอนด์ เฮ้าส์", "เกียรตินาคิน": "เกียรตินาคินภัทร", "ธกส": "ธ.ก.ส."}
# "ธนาคาร B", "ธนาคารบี": a bank not in the list, named after the word ธนาคาร.
OTHER_BANK = re.compile(r"ธนาคาร\s*([a-z]{1,4}(?![a-z])|(?:บี|เอ|ซี|ดี)(?![งกม]))")   # not "ธนาคารเอง", "ธนาคารดีมาก"
NOT_A_BANK_NAME = ("อื่น", "ใหม่", "นี้", "เดิม")


def _words_to_number(words: str) -> str:
    """"สามจุดสองห้า" -> "3.25", "ห้าพัน" -> "5000", "ยี่สิบสี่" -> "24", "สองสี่" -> "24"."""
    whole, _, decimals = words.partition("จุด")
    tokens = TOKEN.findall(whole)
    if tokens and not any(t in UNITS for t in tokens):          # said digit by digit
        number = "".join(str(DIGITS[t]) for t in tokens)
    else:
        total, current = 0, None
        for t in tokens:
            if t in DIGITS:
                current = DIGITS[t]
            elif t == "ล้าน":
                total = (total + (current or 0) or 1) * UNITS[t]
                current = None
            else:
                total += (1 if current is None else current) * UNITS[t]
                current = None
        number = str(total + (current or 0)) if tokens else "0"
    if decimals:
        number += "." + "".join(str(DIGITS[t]) for t in TOKEN.findall(decimals) if t in DIGITS)
    return number


def with_digits(text: str) -> str:
    """The text with Thai number words written as digits, for reading amounts and periods."""
    return NUMBER_WORDS.sub(lambda m: f" {_words_to_number(m.group())} ", normalize(text))


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _clean(value: float) -> str:
    return f"{value:g}" if value != int(value) else str(int(value))


def bank_name(text: str) -> Optional[str]:
    t = normalize(text).replace(" ", "")
    known = next((name for word, name in BANKS.items() if word in t), None)
    if known:
        return known
    m = OTHER_BANK.search(normalize(text))
    if m and m.group(1) not in NOT_A_BANK_NAME:
        name = {"บี": "B", "เอ": "A", "ซี": "C", "ดี": "D"}.get(m.group(1), m.group(1).upper())
        return f"ธนาคาร {name}"
    return None


def parse_offer(text: str) -> dict:
    """{"new_bank_name", "new_interest_rate", "cashback_offered", "promotion_period_months"}: the
    ones said in `text` (as strings, as Genesys participant data wants them)."""
    t, found = with_digits(text), {}
    bank = bank_name(text)
    if bank:
        found["new_bank_name"] = bank
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|เปอร์เซ็น|เปอร์|ต่อปี)", t)
    if m and _number(m.group(1)) < 30:
        found["new_interest_rate"] = _clean(_number(m.group(1)))
    m = re.search(r"(?:เงินคืน|คืนเงิน|แคชแบ็ก|แคชแบ็ค|แคชแบค|cashback|cash back)\D{0,12}?(\d[\d,]*(?:\.\d+)?)", t) \
        or re.search(r"(\d[\d,]*)\s*บาท", t)
    if m and _number(m.group(1)) >= 100:
        found["cashback_offered"] = _clean(_number(m.group(1)))
    m = re.search(r"(?:โปร|โปรโมชั่น|โปรโมชัน|คงที่|นาน|ระยะ)\D{0,12}?(\d+)\s*(เดือน|ปี)", t) \
        or re.search(r"(\d+)\s*(ปี)\s*แรก", t)
    if m:
        months = int(m.group(1)) * (12 if m.group(2) == "ปี" else 1)
        found["promotion_period_months"] = str(months)
    return found


def parse_days(text: str, today: date, anywhere: bool = True) -> Optional[int]:
    """How many days until the customer must close: "ภายใน 5 วัน" -> 5, "อาทิตย์หน้า" -> 7,
    "สิ้นเดือน" -> days left in the month. `anywhere`=False: the answer to "ภายในกี่วัน", so a bare
    "5 วัน" counts; otherwise only with "ภายใน" / "อีก" in front."""
    t = with_digits(text).replace(" ", "")
    lead = "" if not anywhere else r"(?:ภายใน|อีก|ไม่เกิน)"
    m = re.search(lead + r"(\d+)(วัน|สัปดาห์|อาทิตย์|เดือน)", t)
    if m:
        return int(m.group(1)) * {"วัน": 1, "สัปดาห์": 7, "อาทิตย์": 7, "เดือน": 30}[m.group(2)]
    if "สิ้นเดือน" in t or "ภายในเดือนนี้" in t:
        return calendar.monthrange(today.year, today.month)[1] - today.day
    if anywhere:
        return None
    for words, days in (("พรุ่งนี้", 1), ("วันนี้", 0), ("สัปดาห์หน้า", 7), ("อาทิตย์หน้า", 7), ("เดือนหน้า", 30)):
        if words in t:
            return days
    return None
