"""The conversation engine for a bank call center. It is channel-free: web chat and the
phone line (Genesys) both call Bot.reply(session_id, text) and render the Reply their own way.

What the bot does, and what it leaves to people:
- INQUIRIES it answers itself, once the customer is verified: amounts due, loans, credit cards,
  deposit balances, the status of their own case. General questions (FAQ, hours, payment channels)
  need no verification.
- REQUESTS that open work (close or refinance a loan, apply for a card, raise a limit, cancel a card,
  transactions, complaints, lost cards...) go to an agent: the bot confirms what the customer wants,
  verifies them, then hands over with what it learned. It never opens cases itself.

Each turn:
1. "ขอคุยกับเจ้าหน้าที่": verify first if possible, then hand over (asked again: hand over now).
2. "ยกเลิก" on its own leaves the current step.
3. Inside a step (waiting for an ID number, a yes/no...) the answer to that step is read.
   A line that is clearly about another topic switches topic instead.
4. Otherwise the topic is detected and its handler answers, verifies, or hands over.
5. Nothing understood: apologise, and after a couple of misses offer a person.
"""
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import backend, config, db
from .intents import detect, is_cancel, is_filler, is_fragment, is_polite_only, keyword_score, yes_no
from .normalize import compact, digits_only, normalize, phone_from_ani
from .offers import bank_name, parse_days, parse_offer
from .privacy import mask_digits
from .tables import valid_national_id
from .thai_format import baht, speech_text, thai_date

P, Q, ME = config.STATEMENT_PARTICLE, config.QUESTION_PARTICLE, config.SELF

NATIONAL_ID = re.compile(r"(?<!\d)\d{13}(?!\d)")
ID_LAST4 = re.compile(r"(?<!\d)\d{4}(?!\d)")
HISTORY_TURNS = 60          # lines kept for the transcript (customer and bot)
# What the summary for the agent calls each topic.
TOPIC_NAMES = {"balance_due": "ยอดค้างชำระ", "loan_info": "ข้อมูลสินเชื่อ", "card_info": "วงเงินบัตร",
               "deposit_balance": "ยอดเงินในบัญชี", "case_status": "สถานะเรื่อง", "payment_channels": "ช่องทางชำระ",
               "hours": "เวลาทำการ"}
# A case number as customers say or type it: "CS0001001", "ซีเอส 1001", or the old "TK1001".
TICKET_NO = re.compile(r"(?i)(?<![a-z])(?:cs|tk|ซีเอส|ซี เอส|ทีเค|ที เค)\s*-?\s*(\d{4,7})")
CASE_DIGITS = re.compile(r"(?<!\d)(\d{4,7})(?!\d)")
THAI_TIME = timezone(timedelta(hours=7))

INQUIRIES = ("balance_due", "loan_info", "card_info", "deposit_balance", "case_status")
# Requests an agent handles: what the bot calls them when it confirms and hands over.
REQUESTS = {
    "loan_close": "ปิดบัญชีสินเชื่อ",
    "card_apply": "สมัครบัตรเครดิต",
    "card_limit": "เพิ่มวงเงินบัตรเครดิต",
    "card_cancel": "ยกเลิกบัตรเครดิต",
    "transaction_help": "ทำธุรกรรมโอน ฝาก หรือถอนเงิน",
    "complaint": "แจ้งปัญหาการใช้งานหรือร้องเรียนการให้บริการ",
    "loan_rate_review": "ขอพิจารณาอัตราดอกเบี้ยสินเชื่อ",
    "loan_restructure": "ขอปรับโครงสร้างหนี้หรือลดค่างวด",
    "deposit_close": "ปิดบัญชีเงินฝาก",
}
# Requests about a loan: after the identity check the bot finds which loan, for the agent.
LOAN_REQUESTS = ("loan_close", "loan_refinance", "loan_rate_review", "loan_restructure")
# Why a loan is closed (what the retention team needs most). First match wins.
CLOSE_REASONS = (
    ("ไม่ระบุ", ("ไม่สะดวก", "ไม่บอก", "ไม่ขอตอบ", "ส่วนตัว", "ไม่แน่ใจ", "ไม่ต้องรู้")),
    ("รีไฟแนนซ์ไปธนาคารอื่น", ("รีไฟแนน", "refinance", "ย้าย", "ธนาคารอื่น", "แบงก์อื่น", "แบงค์อื่น", "ที่อื่น",
                               "ดอกถูก", "ดอกเบี้ยถูก", "ดอกเบี้ยต่ำ", "ดอกต่ำ", "ข้อเสนอดีกว่า")),
    ("ดอกเบี้ยสูง", ("ดอกเบี้ยสูง", "ดอกสูง", "ดอกเบี้ยแพง", "ดอกแพง")),
    ("ภาระค่างวดสูง", ("ผ่อนไม่ไหว", "ค่างวดสูง", "ภาระ", "ไม่ไหว")),
    ("ขายหลักทรัพย์", ("ขายบ้าน", "ขายคอนโด", "ขายที่", "ขายทรัพย์", "ขาย")),
    ("ปิดยอดด้วยเงินตัวเอง", ("ปิดเอง", "ปิดยอดเอง", "เงินก้อน", "โปะ", "มีเงิน", "จ่ายหมด", "หมดหนี้", "ไม่อยากเป็นหนี้",
                              "เงินตัวเอง", "เงินเก็บ")),
)
LOAN_TYPES = (("บ้าน", "บ้าน"), ("คอนโด", "บ้าน"), ("ส่วนบุคคล", "ส่วนบุคคล"), ("ส่วนตัว", "ส่วนบุคคล"))
# "Let me think about it": not now. The bot leaves the door open (and offers a rate review).
HESITATE = ("ขอคิดก่อน", "ขอคิดดูก่อน", "คิดดูก่อน", "ขอคิดดู", "ไว้ก่อน", "ยังไม่ปิด", "ยังไม่อยากปิด", "ยังไม่ตัดสินใจ")
# Calling about someone else's account, or a death: an agent checks who may act.
ON_BEHALF = ("ของแม่", "ของพ่อ", "ของคุณแม่", "ของคุณพ่อ", "ของสามี", "ของภรรยา", "ของภรรยา", "ของแฟน", "ของลูก",
             "ของญาติ", "ของยาย", "ของตา", "โทรแทน", "ติดต่อแทน", "ทำแทน", "แทนแม่", "แทนพ่อ", "แทนเจ้าของ")
DECEASED = ("เสียชีวิต", "ถึงแก่กรรม")
# The close reason as ServiceNow's PayOff flow reads it (participant data "reason").
REASON_CODES = {"รีไฟแนนซ์ไปธนาคารอื่น": "refinance", "ปิดยอดด้วยเงินตัวเอง": "own_funds",
                "ขายหลักทรัพย์": "sell_property", "ภาระค่างวดสูง": "high_installment",
                "ดอกเบี้ยสูง": "high_interest", "ไม่ระบุ": "not_given"}
LOAN_CLOSED = "ปิดแล้ว"          # loans.status of a closed loan (ServiceNow mock: loan_status "closed")
DONT_KNOW = ("ไม่ทราบ", "ไม่รู้", "ยังไม่รู้", "ยังไม่ทราบ", "ไม่แน่ใจ", "ยังไม่ได้คุย", "ยังไม่ได้ถาม", "ข้าม",
             "ไม่บอก", "ไม่สะดวก", "ไม่มี", "ไม่รีบ", "ยังไม่กำหนด")
# Urgent requests: no confirmation question, straight to verification and an agent.
URGENT = {
    "card_lost": ("แจ้งบัตรหายหรือถูกขโมย",
                  f"{ME}จะโอนให้เจ้าหน้าที่ระงับบัตรโดยด่วน{P}"),
    "unauthorized": ("แจ้งรายการที่ไม่ได้ทำ", f"{ME}จะโอนให้เจ้าหน้าที่ตรวจสอบรายการโดยด่วน{P}"),
}
# The menu buttons (and the same words said alone): a narrower question, or an inquiry.
LOAN_MENU = (f"สอบถามข้อมูลสินเชื่อ หรือปิดบัญชี รีไฟแนนซ์{Q}",
             ["ข้อมูลสินเชื่อ", "ปิดบัญชีสินเชื่อ", "รีไฟแนนซ์"])
CATEGORIES = {
    "ยอดค้างชำระ": "balance_due",
    "สินเชื่อและรีไฟแนนซ์": LOAN_MENU,
    "สินเชื่อ": LOAN_MENU,
    "บัตรเครดิต": (f"สอบถามวงเงิน สมัครบัตร เพิ่มวงเงิน หรือยกเลิกบัตร{Q}",
                   ["วงเงินบัตรเครดิต", "สมัครบัตรเครดิต", "เพิ่มวงเงิน", "ยกเลิกบัตรเครดิต"]),
    "บัญชีเงินฝาก": (f"สอบถามยอดเงินในบัญชี หรือธุรกรรมโอน ฝาก ถอน{Q}",
                     ["ยอดเงินในบัญชี", "โอนเงิน", "รายการผิดปกติ"]),
    "แจ้งปัญหาและร้องเรียน": (f"แจ้งบัตรหาย รายการที่ไม่ได้ทำ ปัญหาการใช้งาน หรือติดตามเรื่องที่แจ้ง{Q}",
                              ["แจ้งบัตรหาย", "รายการที่ไม่ได้ทำ", "แจ้งปัญหาการใช้งาน", "ติดตามเรื่องที่แจ้ง"]),
}
# Short answers to a menu question ("สอบถาม" after the deposit menu): the first word found decides.
MENU_CHOICES = {
    "บัญชีเงินฝาก": (("ผิดปกติ", "unauthorized"), ("ไม่ได้ทำ", "unauthorized"), ("โอน", "transaction_help"),
                     ("ถอน", "transaction_help"), ("ฝาก", "transaction_help"), ("ยอด", "deposit_balance"),
                     ("คงเหลือ", "deposit_balance"), ("เช็ค", "deposit_balance"), ("เช็ก", "deposit_balance"),
                     ("สอบถาม", "deposit_balance"), ("ถาม", "deposit_balance")),
    "สินเชื่อ": (("ปิด", "loan_close"), ("รีไฟแนน", "loan_close"), ("ย้าย", "loan_close"), ("ยอด", "loan_info"),
                 ("ข้อมูล", "loan_info"), ("ดอกเบี้ย", "loan_info"), ("สอบถาม", "loan_info"), ("ถาม", "loan_info")),
    "บัตรเครดิต": (("ยกเลิก", "card_cancel"), ("สมัคร", "card_apply"), ("เพิ่ม", "card_limit"), ("ยอด", "card_info"),
                   ("วงเงิน", "card_info"), ("สอบถาม", "card_info"), ("ถาม", "card_info")),
    "แจ้งปัญหาและร้องเรียน": (("หาย", "card_lost"), ("ขโมย", "card_lost"), ("ไม่ได้ทำ", "unauthorized"),
                              ("ติดตาม", "case_status"), ("ตาม", "case_status"), ("ปัญหา", "complaint"),
                              ("ร้องเรียน", "complaint")),
    "ยอด": (("ค้าง", "balance_due"), ("ชำระ", "balance_due"), ("บัตร", "balance_due"), ("แรก", "balance_due"),
            ("บัญชี", "deposit_balance"), ("เงิน", "deposit_balance"), ("หลัง", "deposit_balance")),
}
MENU_CHOICES["สินเชื่อและรีไฟแนนซ์"] = MENU_CHOICES["สินเชื่อ"]
MENU_CHOICES["ปิดบัญชี"] = (("สินเชื่อ", "loan_close"), ("บ้าน", "loan_close"), ("กู้", "loan_close"),
                            ("ฝาก", "deposit_close"), ("ออม", "deposit_close"))
# A bare "ปิดบัญชี": which account?
CLOSE_MENU = (f"ปิดบัญชีสินเชื่อ หรือบัญชีเงินฝาก{Q}", ["ปิดบัญชีสินเชื่อ", "ปิดบัญชีเงินฝาก"])
# A bare "ยอด" / "เช็คยอด": which one?
AMOUNT_MENU = (f"ยอดค้างชำระ หรือยอดเงินในบัญชี{Q}", ["ยอดค้างชำระ", "ยอดเงินในบัญชี"])


def menu_question(menu: str):
    """(question, buttons) of a menu the bot asked."""
    return {"ยอด": AMOUNT_MENU, "ปิดบัญชี": CLOSE_MENU}.get(menu) or CATEGORIES[menu]
DIGIT_STEPS = ("need_national_id", "need_id4", "need_case")
# Steps that ask yes/no about an offer: any other answer is a new request.
OFFER_STEPS = ("confirm_next", "anything_else")
YES_NO_STEPS = ("confirm_intent", "confirm_next")
MORE = f"มีอะไรให้ช่วยเพิ่มเติมไหม{Q}"


@dataclass
class Reply:
    text: str
    quick_replies: list = field(default_factory=list)
    intent: Optional[str] = None
    handoff: bool = False  # the channel should pass the customer to a human agent
    end: bool = False  # the conversation is over
    expects: Optional[str] = None  # "digits": the bot is waiting for a number (show a keypad)
    speech: str = ""  # the same reply worded for text-to-speech (numbers read the way people say them)
    context: dict = field(default_factory=dict)  # on handoff: what the agent should know

    def __post_init__(self):
        if not self.speech:
            self.speech = speech_text(self.text, config.SAY_AS, keep_together=tuple(filter(None, [config.BRAND])))

    def to_dict(self):
        return asdict(self)


@dataclass
class Session:
    flow: Optional[str] = None  # what we are helping with
    step: Optional[str] = None  # what we are waiting for: need_national_id, confirm_intent, ...
    slots: dict = field(default_factory=dict)
    verified_id: Optional[str] = None  # national ID, once verified (kept for the conversation)
    verified_phone: Optional[str] = None  # that customer's registered phone (for the agent)
    customer_name: Optional[str] = None
    first_name: str = ""  # said back to the customer: "ขอบคุณครับคุณพลอยใส"
    menu: Optional[str] = None  # the menu question just asked, so short answers ("สอบถาม") make sense
    fillers: int = 0  # "เอ่อ", "ครับ"... in a row
    misunderstood: int = 0
    retries: int = 0
    verify_attempts: int = 0
    # Recent turns as ("user" | "assistant", text), personal numbers masked. Read by the AI fallback.
    history: list = field(default_factory=list)
    context: dict = field(default_factory=dict)  # request and case talked about, passed on at handoff
    channel: str = "web"  # "phone" for Genesys calls
    case_misses: int = 0  # case numbers not found or not the customer's: stops guessing
    caller_phone: str = ""  # the number the customer calls from (Genesys ANI), when known
    verified_by: str = ""  # how identity was checked, for the agent's summary
    topics: list = field(default_factory=list)  # what was asked about, in order
    last_active: float = field(default_factory=time.time)

    def leave_flow(self):
        self.flow, self.step, self.slots, self.retries = None, None, {}, 0


class Bot:
    def __init__(self, fallback: Optional[Callable[[str, Session], Optional[str]]] = None,
                 session_ttl: int = 30 * 60, clock: Optional[Callable[[], datetime]] = None):
        """`fallback(message, session)` may return a reply for lines no rule understood,
        e.g. from an LLM or an FAQ search. Leave it None for rules only.
        `clock()` gives the current Thai time (tests pass a fixed one)."""
        self.fallback = fallback
        self.session_ttl = session_ttl
        self.clock = clock or (lambda: datetime.now(THAI_TIME))
        self.sessions = {}
        self._lock = threading.Lock()

    # ---- public -------------------------------------------------------------------------
    def reply(self, session_id: str, message: str) -> Reply:
        with self._lock:
            self._expire_old_sessions()
            s = self.sessions.get(session_id)
            if s is None:
                s = self.sessions[session_id] = Session(
                    channel="phone" if session_id.startswith("genesys") else "web")
            s.last_active = time.time()
            reply = self._reply(s, session_id, message)
            if reply.end:
                self.sessions.pop(session_id, None)
            if s.step in DIGIT_STEPS:
                reply.expects = "digits"
            topic = reply.intent if reply.intent in TOPIC_NAMES or reply.intent in REQUESTS else None
            if topic and topic not in s.topics:
                s.topics.append(topic)
            if normalize(message):  # kept even when the conversation ends, for the transcript
                s.history += [("user", mask_digits(normalize(message))), ("assistant", reply.text)]
                del s.history[:-HISTORY_TURNS]
            return reply

    @staticmethod
    def is_registered_phone(phone: str) -> bool:
        return bool(phone) and backend.customer_by_phone(phone) is not None

    def set_caller(self, session_id: str, ani) -> None:
        """The number the customer calls from (Genesys ANI, e.g. "tel:+66815493626"). When it is a
        customer's registered phone, the identity check asks only for the last 4 ID digits."""
        with self._lock:
            s = self.sessions.get(session_id)
            if s is None:
                s = self.sessions[session_id] = Session(
                    channel="phone" if session_id.startswith("genesys") else "web")
            s.caller_phone = phone_from_ani(ani)

    def welcome(self) -> Reply:
        # Short on purpose; it still says the caller is talking to an automated assistant.
        brand = f" {config.BRAND}" if config.BRAND else ""
        return Reply(f"สวัสดี{P} ผู้ช่วยอัตโนมัติ{brand} ต้องการติดต่อเรื่องใด{Q}",
                     config.MAIN_MENU, "greeting")

    def reset(self, session_id: str):
        with self._lock:
            self.sessions.pop(session_id, None)

    # ---- turn logic ---------------------------------------------------------------------
    def _reply(self, s: Session, session_id: str, message: str) -> Reply:
        if not normalize(message):
            return Reply(f"ต้องการติดต่อเรื่องใด{Q}", config.MAIN_MENU)

        intent, faq = self._detect(message)
        if intent == "agent":
            return self._on_agent(s, message)
        if is_filler(message) or (not intent and not s.step and not s.menu and is_fragment(message)):
            return self._on_filler(s, message)
        s.fillers = 0
        key = compact(message)
        if any(w in key for w in DECEASED):
            return self._for_someone_else(s, intent, "deceased", "แจ้งเจ้าของบัญชีเสียชีวิต",
                                          f"ขอแสดงความเสียใจด้วย{P} {ME}จะโอนให้เจ้าหน้าที่ดูแลต่อ{P}")
        if any(w in key for w in ON_BEHALF) and (intent or s.flow):
            return self._for_someone_else(s, intent, "third_party", "โทรแทนเจ้าของบัญชี",
                                          f"เรื่องบัญชีของผู้อื่น ต้องให้เจ้าหน้าที่ตรวจสอบสิทธิ์ก่อน{P}")
        if s.flow and is_cancel(message):
            s.leave_flow()
            return self._more(s, Reply(f"ยกเลิกแล้ว{P}", config.MAIN_MENU, "cancel"))
        if s.flow:
            reply = self._continue_flow(s, message, intent, faq)
            if reply:
                return reply
            s.leave_flow()  # the customer moved on to another topic

        menu, s.menu = s.menu, None
        category = CATEGORIES.get(key)
        if isinstance(category, tuple):
            s.misunderstood, s.menu = 0, key
            return Reply(category[0], category[1], "menu")
        if isinstance(category, str):
            intent = category
        if menu and (not intent or menu in ("ยอด", "ปิดบัญชี")):    # "เงินฝาก" after "ปิดบัญชีอะไร": closing
            intent = next((topic for word, topic in MENU_CHOICES.get(menu, ()) if word in key), None) or intent
        if not intent and "ยอด" in key and len(key) <= 12:
            s.menu = "ยอด"
            return Reply(*AMOUNT_MENU, "menu")
        if not intent and re.search("(?<!เ)ปิดบัญชี", key) and len(key) <= 16:
            s.menu = "ปิดบัญชี"
            return Reply(*CLOSE_MENU, "menu")
        if intent == "faq":
            s.misunderstood = 0
            return self._on_faq(s, message, faq)
        handler = getattr(self, f"_on_{intent}", None) if intent else None
        if handler:
            s.misunderstood = 0
            reply = handler(s, message)
            if reply.end:
                self.sessions.pop(session_id, None)
            return reply
        if intent in REQUESTS:
            s.misunderstood = 0
            return self._confirm_request(s, intent, message)
        if intent in URGENT:
            s.misunderstood = 0
            what, lead = URGENT[intent]
            return self._request(s, intent, what, lead)
        return self._not_understood(s, message, menu)

    def _detect(self, message: str):
        """(topic, faq entry). A case number means case_status; an FAQ entry wins when its
        keywords match more strongly than the built-in topics."""
        intent, score = detect(message)
        if intent != "agent" and TICKET_NO.search(message):
            return "case_status", None
        best, best_score = None, 0
        for entry in backend.faq_entries():
            entry_score = keyword_score(entry["keywords"], message)
            if entry_score > best_score:
                best, best_score = entry, entry_score
        if best and best_score > score:
            return "faq", best
        return intent, None

    def _continue_flow(self, s: Session, message: str, intent: Optional[str], faq=None) -> Optional[Reply]:
        if intent == "faq" and faq and faq["action"] == "answer" and s.step not in OFFER_STEPS:
            # A side question in the middle ("ปิดก่อนกำหนดมีค่าปรับไหม"): answer it, then carry on.
            reply = getattr(self, f"_step_{s.step}")(s, message)
            if reply:
                return self._prefixed(faq["answer"], reply)
            return Reply(f"{faq['answer']} {self._ask(s).text}", self._ask(s).quick_replies, s.flow)
        reply = getattr(self, f"_step_{s.step}")(s, message)
        if reply:
            return reply
        if s.step in OFFER_STEPS:
            return None  # not a yes or no: the customer asks something else
        # Not the answer we asked for. A clear new topic switches to it; anything else re-asks.
        if intent and intent not in (s.flow, "thanks", "greeting"):
            return None
        s.retries += 1
        if s.retries > config.MAX_MISUNDERSTOOD:
            pending = s.slots.get("then") or {}
            if pending.get("kind") == "handoff":
                s.context["request"] = pending.get("detail", "")
            flow = s.flow
            s.leave_flow()
            s.flow, s.step = flow, "confirm_next"
            s.slots = {"yes": "handoff_now", "reason": pending.get("reason") or "agent"}
            return Reply(f"ขอโทษ{P} ให้{ME}ต่อสายเจ้าหน้าที่ช่วยดูแลไหม{Q}", ["ใช่", "ไม่ใช่"], flow)
        return self._ask(s, again=True)

    def _ask(self, s: Session, again: bool = False) -> Reply:
        """The current step's question. Asked again, it is worded differently (people repeat
        themselves in other words, not word for word)."""
        prompts = {
            "need_national_id": (f"ขอเลขบัตรประชาชน 13 หลัก{P}",
                                 f"รบกวนพูดเลขบัตรประชาชนทีละตัว ให้ครบ 13 หลัก{P}"),
            "need_id4": (f"ขอเลขบัตรประชาชน 4 ตัวท้าย{P}",
                         f"รบกวนพูดเลข 4 ตัวท้ายของบัตรประชาชนอีกครั้ง{P}"),
            "confirm_intent": (f"ต้องการ{s.slots.get('what', '')} ใช่ไหม{Q}",
                               f"ตอบว่า ใช่ หรือ ไม่ใช่ ได้เลย{P}"),
            "loan_mode": (f"ปิดบัญชีเลย หรือสอบถามรายละเอียดก่อน{Q}",
                          f"ต้องการปิดบัญชีเลย หรืออยากสอบถามรายละเอียดก่อน{Q}"),
            "loan_reason": (f"ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเอง{Q}",
                            f"ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเอง{Q}"),
            "loan_offer": (f"ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่{Q}", f"ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่{Q}"),
            "loan_when": (f"ต้องการปิดบัญชีภายในกี่วัน{Q}", f"ต้องการปิดบัญชีภายในกี่วัน{Q}"),
            "which_loan": (self._which_loan_question(s), self._which_loan_question(s)),
            "need_case": (f"ขอเลขที่เรื่อง ที่ขึ้นต้นด้วย CS{P}",
                          f"รบกวนพูดเลขที่เรื่องอีกครั้ง เช่น ซีเอส หนึ่งศูนย์ศูนย์หนึ่ง{P}"),
            "confirm_next": (f"ใช่ หรือไม่ใช่{Q}", f"ตอบว่า ใช่ หรือ ไม่ใช่ ได้เลย{P}"),
            "anything_else": (f"มีเรื่องอื่นให้ช่วยไหม{Q}", f"มีเรื่องอื่นให้ช่วยไหม{Q}"),
        }
        quick = {"confirm_intent": ["ใช่", "ไม่ใช่"], "confirm_next": ["ใช่", "ไม่ใช่"],
                 "loan_mode": ["ปิดบัญชีเลย", "สอบถามรายละเอียดก่อน"],
                 "loan_reason": ["ย้ายไปธนาคารอื่น", "ปิดยอดเอง", "ไม่สะดวกบอก"],
                 "which_loan": [f"ลงท้าย {n[-4:]}" for n in s.slots.get("loans", [])],
                 "anything_else": config.MAIN_MENU + ["จบการสนทนา"]}.get(s.step, ["ยกเลิก"])
        first, second = prompts[s.step]
        text = second if again and s.retries >= 2 else f"ขอโทษ{P} {first}" if again else first
        return Reply(text, quick, s.flow)

    # ---- identity check: the 13-digit national ID number --------------------------------
    def _verify_then(self, s: Session, then: dict, lead: str = "") -> Reply:
        """Run `then` now if the customer is verified, else ask for the ID number first.
        then = {"kind": "inquiry", "intent": ..., "message": ...}
             | {"kind": "handoff", "reason": ..., "lead": ..., "detail": ...}"""
        if s.verified_id:
            return self._after_verify(s, then)
        lead = f"{lead} " if lead else ""
        intent = then.get("intent") or then.get("reason")
        caller = backend.customer_by_phone(s.caller_phone) if s.caller_phone else None
        if caller:   # calling from their registered phone: the last 4 ID digits are enough
            s.flow, s.step, s.retries = "verify", "need_id4", 0
            s.slots = {"then": then, "candidate": caller["national_id"]}
            return Reply(f"{lead}ขอเลขบัตรประชาชน 4 ตัวท้าย เพื่อยืนยันตัวตน{P}", ["ยกเลิก"], intent)
        s.flow, s.step, s.retries, s.slots = "verify", "need_national_id", 0, {"then": then}
        return Reply(f"{lead}ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตน{P}", ["ยกเลิก"], intent)

    def _step_need_id4(self, s: Session, message: str) -> Optional[Reply]:
        """Caller's registered phone + last 4 ID digits. The full 13 digits are accepted too."""
        if NATIONAL_ID.search(digits_only(message)):
            return self._step_need_national_id(s, message)
        m = ID_LAST4.search(digits_only(message))
        if not m:
            return None
        national_id, now, then = s.slots["candidate"], self.clock(), s.slots.get("then")
        if backend.verify_locked(national_id, now):
            return self._verify_failed(s, then, "verify_locked", f"ตอนนี้ยืนยันตัวตนอัตโนมัติไม่ได้{P}")
        if national_id[-4:] == m.group():
            return self._verified(s, backend.find_customer(national_id), then, "เบอร์ที่โทรเข้า + เลขบัตร 4 ตัวท้าย")
        backend.record_verify_failure(national_id, now)
        s.verify_attempts += 1
        if s.verify_attempts >= config.MAX_VERIFY_ATTEMPTS or backend.verify_locked(national_id, now):
            return self._verify_failed(s, then, "verify_failed", f"ยืนยันตัวตนไม่สำเร็จ{P}")
        return Reply(f"ข้อมูลไม่ตรงกับในระบบ{P} ขอเลขบัตร 4 ตัวท้ายอีกครั้ง{P}", ["ยกเลิก"], "verify")

    def _verified(self, s: Session, customer: dict, then: Optional[dict], how: str) -> Reply:
        backend.clear_verify_failures(customer["national_id"])
        caller = backend.customer_by_phone(s.caller_phone) if s.caller_phone else None
        calling_from_own = caller and caller["national_id"] == customer["national_id"]
        s.verified_id, s.verified_by = customer["national_id"], how
        s.verified_phone = s.caller_phone if calling_from_own else customer["phone"]   # the number ServiceNow matches
        s.customer_name = " ".join(filter(None, [f"{customer['title'] or ''}{customer['first_name']}",
                                                 customer["last_name"]]))
        s.first_name = customer["first_name"] or ""
        s.leave_flow()
        s.verify_attempts = 0
        done = self._after_verify(s, then) if then else Reply(f"มีอะไรให้ช่วย{Q}", config.MAIN_MENU)
        return self._prefixed(f"ขอบคุณ{P}{self._you(s)}", done)

    @staticmethod
    def _you(s: Session) -> str:
        """"คุณพลอยใส" once verified, else nothing."""
        return f"คุณ{s.first_name}" if s.first_name else ""

    def _step_need_national_id(self, s: Session, message: str) -> Optional[Reply]:
        m = NATIONAL_ID.search(digits_only(message))
        if not m:
            return None
        national_id, now, then = m.group(), self.clock(), s.slots.get("then")
        if not valid_national_id(national_id):     # a mistyped number: not counted as a failure
            s.retries += 1
            return Reply(f"เลขบัตรไม่ถูกต้อง{P} ขออีกครั้ง{P}", ["ยกเลิก"], "verify")
        if backend.verify_locked(national_id, now):    # too many failures on this ID, from any call
            return self._verify_failed(s, then, "verify_locked",
                                       f"ตอนนี้ยืนยันตัวตนอัตโนมัติไม่ได้{P}")
        customer = backend.find_customer(national_id)
        if customer:
            return self._verified(s, customer, then, "เลขบัตรประชาชน 13 หลัก")
        backend.record_verify_failure(national_id, now)
        s.verify_attempts += 1
        if s.verify_attempts >= config.MAX_VERIFY_ATTEMPTS or backend.verify_locked(national_id, now):
            return self._verify_failed(s, then, "verify_failed", f"ยืนยันตัวตนไม่สำเร็จ{P}")
        return Reply(f"ข้อมูลไม่ตรงกับในระบบ{P} ขอเลขบัตรอีกครั้ง{P}", ["ยกเลิก"], "verify")

    def _verify_failed(self, s: Session, then: Optional[dict], reason: str, lead: str) -> Reply:
        """Could not verify: an agent can check identity another way. Nothing about accounts is said."""
        s.leave_flow()
        if then and then.get("kind") == "handoff":
            s.context["request"] = then.get("detail", "")
        return self._handoff(s, reason, lead=f"{lead} ขอโอนให้เจ้าหน้าที่ดูแลต่อ{P}")

    def _after_verify(self, s: Session, then: dict) -> Reply:
        if then["kind"] == "handoff" and "loan" in then:
            return self._loan_handoff(s, then)
        if then["kind"] == "handoff":
            s.context["request"] = then.get("detail", "")
            return self._handoff(s, then["reason"], lead=then.get("lead", ""))
        return getattr(self, f"_answer_{then['intent']}")(s, then.get("message", ""))

    @staticmethod
    def _prefixed(prefix: str, reply: Reply) -> Reply:
        return Reply(f"{prefix} {reply.text}", reply.quick_replies, reply.intent, reply.handoff, reply.end,
                     reply.expects, context=reply.context)

    # ---- requests: confirm, verify, hand over ---------------------------------------------
    def _confirm_request(self, s: Session, intent: str, message: str) -> Reply:
        what = REQUESTS[intent]
        s.flow, s.step, s.retries, s.slots = intent, "confirm_intent", 0, {"what": what}
        if intent == "loan_close":
            s.slots = {"what": "ปิดบัญชีสินเชื่อ"}
            self._take_close_facts(s, message)
            s.slots["what"] = f"ปิดบัญชีสินเชื่อ{s.slots.get('type', '')}"
            return Reply(f"ต้องการ{s.slots['what']} ใช่ไหม{Q}", ["ใช่", "ไม่ใช่"], intent)
        if intent in LOAN_REQUESTS:
            s.slots["type"] = self._loan_type(message)
        return Reply(f"ต้องการ{what} ใช่ไหม{Q}", ["ใช่", "ไม่ใช่"], intent)

    def _step_confirm_intent(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if s.flow == "loan_close":
            found = self._take_close_facts(s, message)
            if answer is None and found:       # "อยากรู้รายละเอียดก่อน" / "จะย้ายไปกสิกร": a yes, with more
                answer = True
        if answer is None:
            return None
        if not answer:
            other, _ = detect(message)
            if other and other not in (s.flow, "agent"):   # "ไม่ใช่ อยากเช็คยอดค้างชำระ": go there
                return None
            s.leave_flow()
            return Reply(f"ขออภัย{P} ต้องการติดต่อเรื่องใด{Q}", config.MAIN_MENU, "declined")
        if s.flow == "loan_close":
            return self._loan_next(s)
        intent, what, loan_type = s.flow, s.slots["what"], s.slots.get("type")
        s.leave_flow()
        lead = f"{ME}จะโอนให้เจ้าหน้าที่สินเชื่อดูแลต่อ{P}" if intent in LOAN_REQUESTS else \
            f"{ME}จะโอนให้เจ้าหน้าที่ดำเนินการ{P}"
        return self._request(s, intent, what, lead, loan=loan_type if intent in LOAN_REQUESTS else None)

    # ---- closing a loan: the retention case -------------------------------------------------
    @staticmethod
    def _loan_type(message: str) -> str:
        c = compact(message)
        return next((name for word, name in LOAN_TYPES if word in c), "")

    def _take_close_facts(self, s: Session, message: str, asked_mode: bool = False) -> bool:
        """Keep what the customer said about closing (loan type, now or details first, why, which
        bank), whatever question it answered. True when something new was learned."""
        c, learned = compact(message), False
        if not s.slots.get("type") and self._loan_type(message):
            s.slots["type"], learned = self._loan_type(message), True
        bank = bank_name(message)
        if bank and not s.slots.get("bank"):
            s.slots["bank"], learned = bank, True
        offer = {k: v for k, v in parse_offer(message).items() if k != "new_bank_name"}
        if offer:
            s.slots.setdefault("offer", {}).update(offer)
            learned = True
        days = parse_days(message, self._today())
        if days is not None and "days" not in s.slots:
            s.slots["days"], learned = days, True
        reason = next((name for name, words in CLOSE_REASONS if any(w in c for w in words)), None)
        if bank and reason in (None, "ปิดยอดด้วยเงินตัวเอง", "ดอกเบี้ยสูง"):
            reason = "รีไฟแนนซ์ไปธนาคารอื่น"          # a bank named: they are moving
        moving = reason == "รีไฟแนนซ์ไปธนาคารอื่น"      # said later, moving banks outweighs an earlier guess
        if reason and (not s.slots.get("reason") or s.slots["reason"] == "ดอกเบี้ยสูง"
                       or (moving and s.slots["reason"] != reason and not s.slots["reason"].startswith("อื่นๆ"))):
            s.slots["reason"], learned = reason, True
        mode = self._loan_mode(message, strict=not asked_mode)
        if mode and not s.slots.get("mode"):
            s.slots["mode"], learned = mode, True
        return learned

    @staticmethod
    def _loan_mode(message: str, strict: bool = False) -> Optional[str]:
        """Close now, or details first. `strict` (not the answer to that question): only clear words,
        since "ต้องการปิดบัญชี" is how every request starts."""
        c = compact(message)
        details = ("สอบถาม", "รายละเอียด", "เงื่อนไข", "อย่างไร", "ยังไง", "ยอดปิด", "ต้องเตรียม", "เอกสาร")
        now = ("ดำเนินการ", "ปิดเลย", "ทันที", "วันนี้")
        if any(w in c for w in details + (() if strict else ("ก่อน", "ไม่แน่ใจ"))):
            return "สอบถามรายละเอียดก่อน"
        if any(w in c for w in now + (() if strict else ("เลย", "ต้องการปิด", "ปิดบัญชี"))):
            return "ต้องการดำเนินการปิดบัญชี"
        return None

    def _loan_next(self, s: Session, ack: str = "") -> Reply:
        """Ask what is still missing (now or details first, then why), then verify and hand over."""
        ack = f"{ack} " if ack else ""
        if not s.slots.get("mode"):
            s.step, s.retries = "loan_mode", 0
            return Reply(f"{ack}ต้องการปิดบัญชีเลย หรือสอบถามรายละเอียดก่อน{Q}",
                         ["ปิดบัญชีเลย", "สอบถามรายละเอียดก่อน"], "loan_close")
        if not s.slots.get("reason"):
            s.step, s.retries = "loan_reason", 0
            return Reply(f"{ack}ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเอง{Q}",
                         ["ย้ายไปธนาคารอื่น", "ปิดยอดเอง", "ไม่สะดวกบอก"], "loan_close")
        slots = s.slots
        refinance = slots["reason"] == "รีไฟแนนซ์ไปธนาคารอื่น"
        offer = slots.get("offer", {})
        if refinance and not slots.get("asked_offer") and "new_interest_rate" not in offer:
            # What the other bank offers: what the retention team has to beat. Asked once.
            s.step, s.retries, slots["asked_offer"] = "loan_offer", 0, True
            return Reply(f"{ack}ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่{Q}", ["ยังไม่ทราบ"], "loan_close")
        if "days" not in slots and not slots.get("asked_when"):
            s.step, s.retries, slots["asked_when"] = "loan_when", 0, True
            return Reply(f"{ack}ต้องการปิดบัญชีภายในกี่วัน{Q}", ["ภายใน 7 วัน", "ภายใน 30 วัน", "ยังไม่กำหนด"],
                         "loan_close")
        purpose = "เพื่อรีไฟแนนซ์" if refinance else ""
        s.context["reason"] = slots["reason"] + (f" ({slots['bank']})" if slots.get("bank") else "")
        s.context["reason_code"] = REASON_CODES.get(slots["reason"], "other")
        s.context["offer"] = {**({"new_bank_name": slots["bank"]} if slots.get("bank") else {}), **offer}
        if "days" in slots:
            s.context["offer"]["closing_within_days"] = str(slots["days"])
        urgent = slots.get("days") is not None and slots["days"] <= 7
        s.leave_flow()
        return self._request(
            s, "loan_refinance" if refinance else "loan_close", f"{slots['what']}{purpose} ({slots['mode']})",
            lead=f"{ME}จะโอนให้เจ้าหน้าที่ตรวจสอบสินเชื่อ และแนะนำทางเลือกที่เหมาะสม{P}",
            before=f"รับทราบ{P} {ME}จะแจ้งเจ้าหน้าที่ว่าเป็นเรื่องเร่งด่วน{P}" if urgent else f"เข้าใจ{P}",
            loan=slots.get("type", ""))

    def _step_loan_offer(self, s: Session, message: str) -> Optional[Reply]:
        """"ธนาคารใหม่เสนอดอกเบี้ยเท่าไหร่": take what is said (rate, cash back, promotion, bank); asked
        once, never blocks."""
        if any(w in compact(message) for w in HESITATE):
            return self._hesitate(s)
        learned = self._take_close_facts(s, message)
        other, _ = detect(message)
        if not learned and other and other not in ("loan_close", "loan_info", "loan_rate_review", "thanks"):
            return None
        return self._loan_next(s, ack=f"รับทราบ{P}" if learned else "")

    def _step_loan_when(self, s: Session, message: str) -> Optional[Reply]:
        """"ภายในกี่วัน": "5 วัน", "อาทิตย์หน้า", "สิ้นเดือน"... asked once, never blocks."""
        if any(w in compact(message) for w in HESITATE):
            return self._hesitate(s)
        days = parse_days(message, self._today(), anywhere=False)
        self._take_close_facts(s, message)
        if days is not None:
            s.slots["days"] = days
        elif not any(w in compact(message) for w in DONT_KNOW):
            other, _ = detect(message)
            if other and other not in ("loan_close", "loan_info", "thanks"):
                return None
        return self._loan_next(s)

    def _step_loan_mode(self, s: Session, message: str) -> Optional[Reply]:
        c = compact(message)
        if any(w in c for w in HESITATE):
            return self._hesitate(s)
        had_reason = bool(s.slots.get("reason"))
        self._take_close_facts(s, message, asked_mode=True)
        if not s.slots.get("mode") and yes_no(message):
            s.slots["mode"] = "ต้องการดำเนินการปิดบัญชี"
        if s.slots.get("mode"):
            return self._loan_next(s)
        if s.slots.get("reason") and not had_reason:     # answered why, not when: thank, ask again
            return self._loan_next(s, ack=f"รับทราบ{P}")
        return None

    def _step_loan_reason(self, s: Session, message: str) -> Optional[Reply]:
        c = compact(message)
        if any(w in c for w in HESITATE):
            return self._hesitate(s)
        self._take_close_facts(s, message)
        if s.slots.get("reason"):
            return self._loan_next(s)
        other, _ = detect(message)
        if other and other not in ("loan_close", "loan_info", "thanks", "greeting"):
            return None                                   # a new topic: switch to it
        if s.retries == 0:
            s.retries = 1
            return Reply(f"ขอโทษ{P} {self._ask(s).text}", self._ask(s).quick_replies, "loan_close")
        # Still not clear: never block the customer on it. Keep their words for the agent.
        s.slots["reason"] = f"อื่นๆ: {mask_digits(normalize(message))[:60]}"
        return self._loan_next(s)

    def _hesitate(self, s: Session) -> Reply:
        """"ขอคิดดูก่อน": no pressure; offer the retention team's rate review instead."""
        loan_type = s.slots.get("type", "")
        s.leave_flow()
        s.flow, s.step, s.slots = "loan_close", "confirm_next", {"yes": "request:loan_rate_review", "type": loan_type}
        return Reply(f"ได้{P} ระหว่างนี้ให้เจ้าหน้าที่ช่วยดูข้อเสนอดอกเบี้ยให้ไหม{Q}", ["ใช่", "ไม่ใช่"], "loan_close")

    def _loan_handoff(self, s: Session, then: dict) -> Reply:
        """Verified: find the loan the request is about, for the agent; ask which one when unclear."""
        loans = backend.loans(s.verified_id)
        want = then.get("loan") or ""
        if not loans:
            s.context["loan"] = "ไม่พบบัญชีสินเชื่อในระบบ"
            s.context["request"] = then.get("detail", "")
            return self._handoff(s, then["reason"],
                                 lead=f"ไม่พบบัญชีสินเชื่อในชื่อคุณลูกค้า {ME}จะโอนให้เจ้าหน้าที่ตรวจสอบต่อ{P}")
        matching = [l for l in loans if want and want in l["loan_type"]] or loans
        active = [l for l in matching if l["status"] != LOAN_CLOSED]
        if not active:          # already closed (ServiceNow mock C4: the PayOff pre-check fails)
            closed = matching[0]
            s.context.update(request=then.get("detail", ""), loan=self._describe_loan(closed),
                             loan_no=closed["loan_no"])
            s.flow, s.step, s.slots = then["reason"], "confirm_next", {"yes": "handoff_now",
                                                                        "reason": "loan_not_active"}
            return Reply(f"{closed['loan_type']} ลงท้าย {closed['loan_no'][-4:]} ปิดบัญชีไปแล้ว{P} "
                         f"ให้เจ้าหน้าที่ช่วยตรวจสอบต่อไหม{Q}", ["ใช่", "ไม่ใช่"], "loan_info")
        matching = active
        if len(matching) == 1:
            s.context["loan"] = self._describe_loan(matching[0])
            s.context["loan_no"] = matching[0]["loan_no"]
            s.context["request"] = then.get("detail", "")
            return self._handoff(s, then["reason"], lead=then.get("lead", ""))
        s.context["loan"] = " / ".join(self._describe_loan(l) for l in matching)   # if they never say which
        s.flow, s.step, s.retries = then["reason"], "which_loan", 0
        s.slots = {"then": then, "loans": [l["loan_no"] for l in matching],
                   "types": [l["loan_type"] for l in matching]}
        return self._ask(s)

    @staticmethod
    def _which_loan_question(s: Session) -> str:
        names = [f"{t} ลงท้าย {n[-4:]}" for t, n in zip(s.slots.get("types", []), s.slots.get("loans", []))]
        if not names:
            return ""
        return f"เป็นบัญชี{' '.join(names[:-1])} หรือ{names[-1]}{Q}"

    def _step_which_loan(self, s: Session, message: str) -> Optional[Reply]:
        c, numbers, types = compact(message), s.slots["loans"], s.slots["types"]
        then = s.slots["then"]
        m = ID_LAST4.search(digits_only(message))
        picked = [n for n in numbers if m and n.endswith(m.group())]
        picked = picked or [n for n, t in zip(numbers, types) if self._loan_type(message) and self._loan_type(message) in t]
        if not picked and any(w in c for w in ("ทั้งหมด", "ทั้งสอง", "ทุกบัญชี", "ทั้งคู่")):
            picked = list(numbers)
        if not picked and ("แรก" in c or "หนึ่ง" in c):
            picked = numbers[:1]
        if not picked and ("หลัง" in c or "สอง" in c):
            picked = numbers[-1:]
        if not picked:
            return None
        loans = {l["loan_no"]: l for l in backend.loans(s.verified_id)}
        s.context["loan"] = " / ".join(self._describe_loan(loans[n]) for n in picked if n in loans)
        if len(picked) == 1:
            s.context["loan_no"] = picked[0]
        s.context["request"] = then.get("detail", "")
        s.leave_flow()
        return self._handoff(s, then["reason"], lead=then.get("lead", ""))

    @staticmethod
    def _describe_loan(l: dict) -> str:
        """One loan, for the agent's screen (not read aloud)."""
        if l["status"] == LOAN_CLOSED:
            return f"{l['loan_type']} ลงท้าย {l['loan_no'][-4:]} ปิดบัญชีแล้ว"
        parts = [f"{l['loan_type']} ลงท้าย {l['loan_no'][-4:]}", f"คงเหลือ {baht(l['outstanding_principal'])}"]
        if l["interest_rate"] is not None:
            parts.append(f"ดอกเบี้ย {l['interest_rate']:g}%")
        parts.append(f"ค่างวด {baht(l['monthly_installment'])}")
        if l["remaining_months"]:
            parts.append(f"เหลือ {l['remaining_months']} งวด")
        return " ".join(parts)

    def _for_someone_else(self, s: Session, intent: Optional[str], reason: str, note: str, lead: str) -> Reply:
        """About another person's account (or a death): the bot does not verify or answer; an agent
        checks who may act. What it was about goes with the call."""
        what = s.slots.get("what") or REQUESTS.get(intent or "") or TOPIC_NAMES.get(intent or "") \
            or (URGENT[intent][0] if intent in URGENT else "")
        s.leave_flow()
        s.context["request"] = f"{what} ({note})" if what else note
        return self._handoff(s, reason, lead=lead)

    def _request(self, s: Session, reason: str, detail: str, lead: str, before: str = "", loan=None) -> Reply:
        """Verify (if not yet), then hand over to an agent with what the customer wants.
        `loan` (a loan type, "" for any): find the customer's loan for the agent first."""
        then = {"kind": "handoff", "reason": reason, "detail": detail, "lead": lead}
        if loan is not None:
            then["loan"] = loan
        return self._verify_then(s, then, lead=before)

    # ---- inquiries: verified customers only -----------------------------------------------
    def _inquiry(self, s: Session, intent: str, message: str) -> Reply:
        return self._verify_then(s, {"kind": "inquiry", "intent": intent, "message": message})

    def _on_balance_due(self, s, message):
        return self._inquiry(s, "balance_due", message)

    def _on_loan_info(self, s, message):
        return self._inquiry(s, "loan_info", message)

    def _on_card_info(self, s, message):
        return self._inquiry(s, "card_info", message)

    def _on_deposit_balance(self, s, message):
        return self._inquiry(s, "deposit_balance", message)

    def _on_case_status(self, s, message):
        return self._inquiry(s, "case_status", message)

    def _due(self, due) -> str:
        if not due:
            return ""
        late = " เลยกำหนดแล้ว" if due < self._today() else ""
        return f" ครบกำหนด {thai_date(due)}{late}"

    def _answer_balance_due(self, s: Session, message: str) -> Reply:
        c = compact(message)
        only_loans = "สินเชื่อ" in c or "ค่างวด" in c
        only_cards = "บัตร" in c and not only_loans
        lines = []
        if not only_loans:
            lines += [f"บัตร {card['card_name']} ลงท้าย {card['card_no'][-4:]} ยอดค้าง {baht(card['outstanding'])} "
                      f"ขั้นต่ำ {baht(card['minimum_due'])}" + self._due(card["due_date"])
                      for card in backend.credit_cards(s.verified_id) if card["outstanding"] > 0]
        if not only_cards:
            lines += [f"{loan['loan_type']} ค่างวด {baht(loan['monthly_installment'])}" + self._due(loan["next_due_date"])
                      for loan in backend.loans(s.verified_id) if loan["monthly_installment"] > 0]
        if not lines:
            return self._more(s, Reply(f"ไม่มียอดค้างชำระ{P}", config.MAIN_MENU + ["จบการสนทนา"], "balance_due"))
        s.flow, s.step, s.slots = "balance_due", "confirm_next", {"yes": "payment_channels"}
        return Reply("\n".join(f"{line}{P}" for line in lines) + f"\nต้องการช่องทางชำระไหม{Q}",
                     ["ช่องทางชำระเงิน", "จบการสนทนา"], "balance_due")

    def _answer_loan_info(self, s: Session, message: str) -> Reply:
        loans = backend.loans(s.verified_id)
        if not loans:
            return self._more(s, Reply(f"ไม่พบบัญชีสินเชื่อ{P}", config.MAIN_MENU, "loan_info"))
        lines = [f"{l['loan_type']} ลงท้าย {l['loan_no'][-4:]} ปิดบัญชีแล้ว" if l["status"] == LOAN_CLOSED else
                 f"{l['loan_type']} ลงท้าย {l['loan_no'][-4:]} คงเหลือ {baht(l['outstanding_principal'])} "
                 + (f"ดอกเบี้ย {l['interest_rate']:g} เปอร์เซ็นต์ " if l["interest_rate"] is not None else "")
                 + f"ค่างวด {baht(l['monthly_installment'])}" + self._due(l["next_due_date"])
                 + (f" เหลือ {l['remaining_months']} งวด" if l["remaining_months"] else "") for l in loans]
        return self._more(s, Reply("\n".join(f"{line}{P}" for line in lines),
                                   ["ปิดบัญชีสินเชื่อ", "ยอดค้างชำระ", "จบการสนทนา"], "loan_info"))

    def _answer_card_info(self, s: Session, message: str) -> Reply:
        cards = backend.credit_cards(s.verified_id)
        if not cards:
            return self._more(s, Reply(f"ไม่พบบัตรเครดิต{P}", ["สมัครบัตรเครดิต", "จบการสนทนา"], "card_info"))
        lines = [f"บัตร {c['card_name']} ลงท้าย {c['card_no'][-4:]} วงเงินคงเหลือ {baht(c['available_credit'])} "
                 f"จาก {baht(c['credit_limit'])}"
                 + (f" สถานะ{c['status']}" if c["status"] != "ปกติ" else "") for c in cards]
        return self._more(s, Reply("\n".join(f"{line}{P}" for line in lines),
                                   ["ยอดค้างชำระ", "เพิ่มวงเงิน", "จบการสนทนา"], "card_info"))

    def _answer_deposit_balance(self, s: Session, message: str) -> Reply:
        accounts = backend.deposit_accounts(s.verified_id)
        if not accounts:
            return self._more(s, Reply(f"ไม่พบบัญชีเงินฝาก{P}", config.MAIN_MENU, "deposit_balance"))
        lines = [f"บัญชี{a['account_type']} ลงท้าย {a['account_no'][-4:]} คงเหลือ {baht(a['balance'])}"
                 for a in accounts]
        return self._more(s, Reply("\n".join(f"{line}{P}" for line in lines), ["รายการผิดปกติ", "จบการสนทนา"],
                                   "deposit_balance"))

    # ---- the customer's own cases ------------------------------------------------------------
    def _answer_case_status(self, s: Session, message: str) -> Reply:
        m = TICKET_NO.search(message)
        if m:
            return self._case_for(s, db.case_number(m.group(1)))
        s.flow, s.step, s.slots, s.retries = "case_status", "need_case", {}, 0
        return self._ask(s)

    def _step_need_case(self, s: Session, message: str) -> Optional[Reply]:
        m = TICKET_NO.search(message) or CASE_DIGITS.search(digits_only(message))
        if not m:
            return None
        return self._case_for(s, db.case_number(m.group(1)))

    def _case_for(self, s: Session, number: str) -> Reply:
        """Only the verified customer's own cases. One that is not theirs gets the same answer as
        one that does not exist: nothing is said about other people's cases."""
        try:
            case = backend.get_case(number)
        except backend.CaseError:
            return self._handoff(s, "case_error", lead=f"ตอนนี้ตรวจสอบเรื่องไม่ได้{P}")
        if case and not case["consumer"]:
            # No customer on it (e.g. ServiceNow without the owner field): only an agent can check.
            return self._handoff(s, "case_check", lead=f"ขอโอนให้เจ้าหน้าที่ตรวจสอบเรื่องนี้{P}")
        if case and case["consumer"] == s.verified_id:
            return self._show_case(s, case)
        s.case_misses += 1
        if s.case_misses >= config.MAX_CASE_MISSES:
            return self._handoff(s, "case_not_found", lead=f"ไม่พบเรื่องของคุณลูกค้า{P}")
        s.flow, s.step, s.slots, s.retries = "case_status", "need_case", {}, 0
        return Reply(f"ไม่พบเรื่อง {number} ของคุณลูกค้า{P} ขอเลขอีกครั้ง{P}",
                     ["คุยกับเจ้าหน้าที่", "ยกเลิก"], "case_status")

    def _show_case(self, s: Session, case: dict) -> Reply:
        number = case["number"]
        s.leave_flow()
        s.case_misses = 0
        s.context["case"] = number        # passed to the agent only when it is the customer's own
        text = f"เรื่อง {number} {case['status']}{P}"
        if case["done"]:
            if case.get("close_notes"):
                text += f" {case['close_notes']}"
            return self._more(s, Reply(text, config.MAIN_MENU + ["จบการสนทนา"], "case_status"))
        if case["state"] == config.CASE_AWAITING_INFO:   # the agent is waiting for the customer
            s.flow, s.step, s.slots = "case_status", "confirm_next", {"yes": "agent"}
            return Reply(text + f" ต่อสายเจ้าหน้าที่เลยไหม{Q}", ["ใช่", "ไม่ใช่"], "case_status")
        return self._more(s, Reply(text, ["คุยกับเจ้าหน้าที่", "จบการสนทนา"], "case_status"))

    def _step_confirm_next(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if answer is None:
            return None
        slots = s.slots
        topic = slots.get("yes")
        s.leave_flow()
        if answer and topic == "handoff_now":
            return self._handoff(s, slots.get("reason", "agent"))
        if answer and topic and topic.startswith("request:"):
            intent = topic.split(":", 1)[1]
            return self._request(s, intent, REQUESTS[intent], f"{ME}จะโอนให้เจ้าหน้าที่สินเชื่อดูแลต่อ{P}",
                                 loan=slots.get("type", ""))
        if answer and topic:
            return getattr(self, f"_on_{topic}")(s, message)
        return self._more(s, Reply(f"ได้{P}", config.MAIN_MENU + ["จบการสนทนา"], "declined"))

    def _more(self, s: Session, reply: Reply) -> Reply:
        """End an answer the way people do: "anything else?". "ไม่มี" then ends the call."""
        s.flow, s.step, s.slots, s.retries = "more", "anything_else", {}, 0
        joiner = "\n" if "\n" in reply.text else " "
        quick = reply.quick_replies if "จบการสนทนา" in reply.quick_replies else reply.quick_replies + ["จบการสนทนา"]
        return Reply(f"{reply.text}{joiner}{MORE}", quick, reply.intent, context=reply.context)

    def _step_anything_else(self, s: Session, message: str) -> Optional[Reply]:
        """After "มีอะไรให้ช่วยเพิ่มเติมไหม": no -> goodbye, a bare yes -> "go ahead",
        anything else is the next request."""
        topic, _ = detect(message)
        if topic not in (None, "goodbye", "thanks"):
            return None
        answer = yes_no(message)
        if answer is False or topic == "goodbye":
            s.leave_flow()
            return self._on_goodbye(s, message)
        if answer or compact(message) in ("มี", "มีอีก", "มีเพิ่ม", "มีอีกเรื่อง"):
            s.leave_flow()
            return Reply(f"ได้{P} บอกเรื่องที่ต้องการได้เลย{P}", config.MAIN_MENU, "more")
        return None

    # ---- general topics: no verification needed --------------------------------------------
    def _on_greeting(self, s, message):
        return Reply(f"สวัสดี{P} ต้องการติดต่อเรื่องใด{Q}", config.MAIN_MENU, "greeting")

    def _on_payment_channels(self, s, message):
        *first, last = config.PAYMENT_CHANNELS
        space = " " if last[-1].isascii() else ""
        return self._more(s, Reply(f"ชำระได้ทาง{' '.join(first)} หรือ{last}{space}{P}",
                                   config.MAIN_MENU + ["จบการสนทนา"], "payment_channels"))

    def _on_hours(self, s, message):
        now = "" if not config.AGENT_HOURS else (
            f" ขณะนี้อยู่ในเวลาทำการ{P}" if self._agents_open() else f" ขณะนี้อยู่นอกเวลาทำการ{P}")
        return self._more(s, Reply(f"เจ้าหน้าที่ให้บริการ{config.HOURS_TEXT}{P}{now}", config.MAIN_MENU, "hours"))

    def _on_faq(self, s, message, entry):
        """An answer from the faq table; "handoff" entries then verify and hand over."""
        if entry["action"] in ("handoff", "offer_ticket"):     # offer_ticket: from older databases
            return self._request(s, entry["topic"], entry["title"], lead="", before=entry["answer"])
        return self._more(s, Reply(entry["answer"], config.MAIN_MENU + ["จบการสนทนา"], entry["topic"]))

    def _on_thanks(self, s, message):
        return self._more(s, Reply(f"ยินดี{P}", config.MAIN_MENU + ["จบการสนทนา"], "thanks"))

    def _on_goodbye(self, s, message):
        return Reply(f"ขอบคุณ{self._you(s)}ที่ใช้บริการ{P} สวัสดี{P}", [], "goodbye", end=True)

    def _on_filler(self, s: Session, message: str) -> Reply:
        """"เอ่อ", "อ๋อ", "ครับ": the customer is thinking, or speech recognition caught half a word.
        Not a misunderstanding: wait for the rest, kindly."""
        s.fillers += 1
        if s.step in YES_NO_STEPS and is_polite_only(message):    # "...ใช่ไหมครับ" "ครับ" = yes
            s.fillers = 0
            return self._continue_flow(s, "ใช่", None)
        if s.step in DIGIT_STEPS or s.step == "loan_mode":
            return Reply(f"ไม่ต้องรีบ{P} {self._ask(s).text}", self._ask(s).quick_replies, s.flow)
        if s.step:
            return self._ask(s)
        if s.menu:
            question, quick = menu_question(s.menu)
            return Reply(question, quick, "menu")
        if "ฮัลโหล" in compact(message) or "ฮาโหล" in compact(message):
            return Reply(f"ได้ยิน{P} ต้องการติดต่อเรื่องใด{Q}", config.MAIN_MENU, "filler")
        if is_fragment(message):     # cut off mid-word: say so, and let them say it again
            return Reply(f"ขอโทษ{P} ได้ยินไม่ครบ รบกวนพูดอีกครั้ง{P}", config.MAIN_MENU, "filler")
        if s.fillers >= 2:
            return Reply(self._choices(), config.MAIN_MENU, "filler")
        return Reply(f"{P} บอกเรื่องที่ต้องการได้เลย{P}", config.MAIN_MENU, "filler")

    @staticmethod
    def _choices() -> str:
        """The greeting's question again, open: no topics named, so the customer says it their way."""
        return f"ต้องการติดต่อเรื่องอะไร เล่าสั้นๆ ได้เลย{P}"

    # ---- people ---------------------------------------------------------------------------
    def _on_agent(self, s, message):
        """Verify first, so the agent need not ask again; asked again while verifying: hand over now."""
        if s.verified_id or s.flow == "verify":   # both identity steps
            pending = s.slots.get("then") or {}
            s.leave_flow()
            if pending.get("kind") == "handoff":      # keep what they asked for, e.g. card_lost
                s.context["request"] = pending.get("detail", "")
                return self._handoff(s, pending["reason"])
            return self._handoff(s, "agent")
        s.leave_flow()
        return self._verify_then(
            s, {"kind": "handoff", "reason": "agent", "detail": "ขอคุยกับเจ้าหน้าที่", "lead": ""},
            lead=f"ก่อนโอนสาย ไม่สะดวกให้เลขบัตร พูดว่า เจ้าหน้าที่ อีกครั้งได้{P}")

    def _handoff(self, s: Session, reason: str = "agent", lead: str = "") -> Reply:
        """Pass the customer to a person; `reason` becomes the channel's handoffReason.
        Outside AGENT_HOURS (when set), say when agents work instead."""
        s.leave_flow()
        lead = f"{lead} " if lead else ""
        if not self._agents_open():
            return Reply(f"{lead}ตอนนี้นอกเวลาทำการ{P} เจ้าหน้าที่ให้บริการ{config.HOURS_TEXT}{P}",
                         config.MAIN_MENU, "agents_closed")
        context = dict(s.context)
        if s.customer_name:
            context["customerName"] = s.customer_name
        return Reply(f"{lead}กรุณารอสักครู่{P}", [], reason, handoff=True, context=context)

    def _not_understood(self, s: Session, message: str, menu: Optional[str] = None) -> Reply:
        """Ask again the question the customer is answering (a menu's, or the greeting's), not a list
        of examples; a second miss in a row offers a person, as a yes/no question that works by voice."""
        if self.fallback:
            text = self.fallback(message, s)
            if text:
                s.misunderstood = 0
                return Reply(text, config.MAIN_MENU, "fallback")
        key = compact(message)
        if not menu and "ถาม" in key and len(key) <= 20:     # "ขอสอบถามหน่อย": not a miss, just ask what
            return Reply(f"ได้{P} สอบถามเรื่องใด{Q}", config.MAIN_MENU, "menu")
        if s.channel == "phone" and not s.history:
            # The first line of a call is often clipped (the caller talks over the greeting, or
            # speech recognition stops at a pause): ask again, and do not count it as a miss.
            return Reply(f"ขอโทษ{P} เมื่อกี้ได้ยินไม่ชัด รบกวนพูดอีกครั้งได้ไหม{Q}", config.MAIN_MENU, "not_understood")
        s.misunderstood += 1
        if s.misunderstood >= config.MAX_MISUNDERSTOOD:
            s.misunderstood = 0
            s.flow, s.step, s.slots, s.retries = "help", "confirm_next", {"yes": "agent"}, 0
            return Reply(f"ขอโทษอีกครั้ง{P} ให้{ME}ต่อสายเจ้าหน้าที่ช่วยดูแลไหม{Q}",
                         ["ใช่", "ไม่ใช่"], "not_understood")
        if menu:
            s.menu = menu
            question, quick = menu_question(menu)
            return Reply(f"ขอโทษ{P} {question}", quick, "not_understood")
        return Reply(f"ขอโทษ{P} {ME}ยังไม่เข้าใจ รบกวนพูดอีกครั้งสั้นๆ ได้ไหม{Q}", config.MAIN_MENU, "not_understood")

    # ---- time ------------------------------------------------------------------------------
    def _today(self):
        return self.clock().date()

    def _agents_open(self) -> bool:
        if not config.AGENT_HOURS:
            return True
        now = self.clock()
        opens, closes = config.AGENT_HOURS.get(now.weekday(), (0, 0))
        return opens <= now.hour < closes

    def _expire_old_sessions(self):
        cutoff = time.time() - self.session_ttl
        for sid in [sid for sid, s in self.sessions.items() if s.last_active < cutoff]:
            del self.sessions[sid]
