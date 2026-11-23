"""The conversation engine. It is channel-free: web chat (phase 1) and the voice line (phase 2)
both call Bot.reply(session_id, text) and render the Reply their own way.

Each turn:
1. "ขอคุยกับเจ้าหน้าที่" at any time hands the customer to a person.
2. "ยกเลิก" on its own leaves the current step.
3. Inside a step (waiting for a phone number, an order number, ...) the answer to that step is read.
   A line that is clearly about another topic switches topic instead.
4. Otherwise the topic is detected and its handler answers or starts a step.
5. Nothing understood: apologise, show the menu, and after a couple of misses offer a person.
"""
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import backend, config, db
from .intents import detect, is_cancel, keyword_score, yes_no
from .normalize import compact, digits_only, normalize, strip_particles
from .privacy import mask_digits
from .thai_format import baht, mask_phone, speech_text, thai_date

P, Q, ME = config.STATEMENT_PARTICLE, config.QUESTION_PARTICLE, config.SELF

PHONE = re.compile(r"(?<!\d)0\d{8,9}(?!\d)")
ID_LAST4 = re.compile(r"(?<!\d)\d{4}(?!\d)")
ORDER_ID = re.compile(r"(?<!\d)\d{6}(?!\d)")
# A case number as customers say or type it: "CS0001001", "ซีเอส 1001", or the old "TK1001".
TICKET_NO = re.compile(r"(?i)(?<![a-z])(?:cs|tk|ซีเอส|ซี เอส|ทีเค|ที เค)\s*-?\s*(\d{4,7})")
CASE_DIGITS = re.compile(r"(?<!\d)(\d{4,7})(?!\d)")
THAI_TIME = timezone(timedelta(hours=7))
ORDER_FLOWS = ("order_status", "order_cancel", "order_change_address", "order_late",
               "order_not_received", "order_return")
DIGIT_STEPS = ("need_phone", "need_id4", "need_order", "need_ticket", "need_callback")
# Steps that offer something ("open a ticket?"): an answer that is not yes/no is a new request.
OFFER_STEPS = ("confirm_ticket", "confirm_next")


@dataclass
class Reply:
    text: str
    quick_replies: list = field(default_factory=list)
    intent: Optional[str] = None
    handoff: bool = False  # the channel should pass the customer to a human agent
    end: bool = False  # the conversation is over
    expects: Optional[str] = None  # "digits": the bot is waiting for a number (show a keypad)
    speech: str = ""  # the same reply worded for text-to-speech (numbers read digit by digit)
    context: dict = field(default_factory=dict)  # on handoff: what the agent should know (order, ticket)

    def __post_init__(self):
        if not self.speech:
            self.speech = speech_text(self.text, config.SAY_AS, keep_together=(config.BRAND,))

    def to_dict(self):
        return asdict(self)


@dataclass
class Session:
    flow: Optional[str] = None  # what we are helping with: check_balance, order_status, ...
    step: Optional[str] = None  # what we are waiting for: need_phone, need_id4, ...
    slots: dict = field(default_factory=dict)
    verified_phone: Optional[str] = None  # set once identity is confirmed, kept for the session
    context: dict = field(default_factory=dict)  # order / ticket talked about, passed on at handoff
    channel: str = "web"  # recorded on cases as contact_type: "phone" for Genesys calls
    misunderstood: int = 0
    retries: int = 0
    verify_attempts: int = 0
    # Recent turns as ("user" | "assistant", text), personal numbers masked. Read by the AI fallback.
    history: list = field(default_factory=list)
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
            if s.step in DIGIT_STEPS:
                reply.expects = "digits"
            if session_id in self.sessions and normalize(message):  # not ended, not empty
                s.history += [("user", mask_digits(normalize(message))), ("assistant", reply.text)]
                del s.history[:-20]
            return reply

    def welcome(self) -> Reply:
        return Reply(f"สวัสดี{P} {config.BRAND} ยินดีให้บริการ{P} {ME}เป็นผู้ช่วยอัตโนมัติ "
                     f"มีอะไรให้ช่วย{Q}",
                     config.MAIN_MENU, "greeting")

    def reset(self, session_id: str):
        with self._lock:
            self.sessions.pop(session_id, None)

    # ---- turn logic ---------------------------------------------------------------------
    def _reply(self, s: Session, session_id: str, message: str) -> Reply:
        if not normalize(message):
            return Reply(f"มีอะไรให้ช่วย{Q}", config.MAIN_MENU)

        intent, faq = self._detect(message)
        self._topic = intent           # read by steps that must not swallow another topic
        if intent == "agent":
            return self._handoff(s)
        if s.flow and is_cancel(message):
            s.leave_flow()
            return Reply(f"ยกเลิกให้แล้ว{P} มีอะไรให้ช่วยอีกไหม{Q}", config.MAIN_MENU, "cancel")
        if s.flow:
            reply = self._continue_flow(s, message, intent)
            if reply:
                return reply
            s.leave_flow()  # the customer moved on to another topic

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
        return self._not_understood(s, message)

    def _detect(self, message: str):
        """(topic, faq entry). A ticket number means ticket_status; an FAQ entry wins when its
        keywords match more strongly than the built-in topics."""
        intent, score = detect(message)
        if intent != "agent" and TICKET_NO.search(message):
            return "ticket_status", None
        best, best_score = None, 0
        for entry in backend.faq_entries():
            entry_score = keyword_score(entry["keywords"], message)
            if entry_score > best_score:
                best, best_score = entry, entry_score
        if best and best_score > score:
            return "faq", best
        return intent, None

    def _continue_flow(self, s: Session, message: str, intent: Optional[str]) -> Optional[Reply]:
        step_handler = getattr(self, f"_step_{s.step}")
        reply = step_handler(s, message)
        if reply:
            return reply
        if s.step in OFFER_STEPS:
            return None  # not a yes or no: the customer asks something else
        # Not the answer we asked for. A clear new topic switches to it; anything else re-asks.
        if intent and intent not in (s.flow, "thanks", "greeting"):
            return None
        s.retries += 1
        if s.retries > config.MAX_MISUNDERSTOOD:
            return Reply(f"ขออภัย{P} ให้เจ้าหน้าที่ช่วยดูต่อไหม{Q}",
                         ["คุยกับเจ้าหน้าที่", "ยกเลิก"], s.flow)
        return self._ask(s)

    def _ask(self, s: Session) -> Reply:
        prompts = {
            "need_phone": f"ขอเบอร์โทรศัพท์ที่ลงทะเบียนไว้ด้วย{P}",
            "need_id4": f"ขอเลขบัตรประชาชน 4 ตัวท้าย เพื่อยืนยันตัวตนด้วย{P}",
            "need_order": f"ขอเลขคำสั่งซื้อ 6 หลักด้วย{P}",
            "need_problem": f"เล่าปัญหาที่พบให้ฟังหน่อย{P}",
            "confirm_problem": f"ใช่ หรือไม่ใช่{Q}",
            "need_ticket": f"ขอเลขที่เรื่องด้วย{P} เช่น CS0001001",
            "need_callback": f"ขอเบอร์โทรสำหรับติดต่อกลับด้วย{P}",
        }
        quick = ["ใช่", "ไม่ใช่"] if s.step == "confirm_problem" else ["ยกเลิก"]
        return Reply(prompts[s.step], quick, s.flow)

    def _start(self, s: Session, flow: str, step: str) -> Reply:
        s.flow, s.step, s.slots, s.retries = flow, step, {}, 0
        return self._ask(s)

    # ---- steps: each returns a Reply, or None when the line is not the answer asked for --
    def _step_need_phone(self, s: Session, message: str) -> Optional[Reply]:
        m = PHONE.search(digits_only(message))
        if not m:
            return None
        phone = m.group()
        if not backend.find_customer(phone):
            s.retries += 1
            return Reply(f"ไม่พบเบอร์ {mask_phone(phone)} ในระบบ{P} ขอเบอร์อีกครั้งได้ไหม{Q}",
                         ["คุยกับเจ้าหน้าที่", "ยกเลิก"], s.flow)
        s.slots["phone"], s.step, s.retries = phone, "need_id4", 0
        return self._ask(s)

    def _step_need_id4(self, s: Session, message: str) -> Optional[Reply]:
        m = ID_LAST4.search(digits_only(message))
        if not m:
            return None
        if backend.verify_customer(s.slots["phone"], m.group()):
            s.verified_phone, s.verify_attempts = s.slots["phone"], 0
            return self._finish(s)
        s.verify_attempts += 1
        if s.verify_attempts >= config.MAX_VERIFY_ATTEMPTS:
            s.leave_flow()
            return Reply(f"ยืนยันตัวตนไม่สำเร็จ{P} เพื่อความปลอดภัย ขอโอนให้เจ้าหน้าที่ดูแลต่อนะ{Q}",
                         [], "verify_failed", handoff=True)
        return Reply(f"เลขไม่ตรงกับในระบบ{P} ขอเลขบัตร 4 ตัวท้ายอีกครั้ง{P}",
                     ["ยกเลิก"], s.flow)

    def _step_need_order(self, s: Session, message: str) -> Optional[Reply]:
        m = ORDER_ID.search(digits_only(message))
        if not m:
            return None
        order = backend.get_order(m.group())
        if not order:
            s.retries += 1
            return Reply(f"ไม่พบคำสั่งซื้อ {m.group()} {P} ขอเลขอีกครั้งได้ไหม{Q}",
                         ["คุยกับเจ้าหน้าที่", "ยกเลิก"], s.flow)
        purpose, said_first = s.flow, s.slots.get("said", "")
        s.leave_flow()
        s.context["order"] = m.group()
        return self._order_action(s, purpose, m.group(), order, said_first)

    def _order_status_reply(self, s: Session, order_id: str, order: dict) -> Reply:
        delivered = order["status"].startswith("จัดส่งสำเร็จ")
        said = f"คำสั่งซื้อ {order_id} {order['status']}"
        if delivered and order["eta"]:
            said += f"เมื่อวันที่ {thai_date(order['eta'])}"
        elif order["carrier"]:
            said += f"โดย {order['carrier']}"
        said += P if "\u0e00" <= said[-1] <= "\u0e7f" else f" {P}"   # "...Express ค่ะ", "...สินค้าค่ะ"
        if order["eta"] and not delivered:
            said += f" คาดว่าจะได้รับวันที่ {thai_date(order['eta'])}{P}"
        if self._is_late(order):   # proactive: offer to chase it before the customer has to ask
            said += f" ตอนนี้เลยวันที่คาดว่าจะได้รับแล้ว{P} ให้เปิดเรื่องติดตามพัสดุให้ไหม{Q}"
            self._set_offer(s, "order_late", f"พัสดุล่าช้า คำสั่งซื้อ {order_id}", order_id)
        # The tracking number is shown, not read out: a long code is hard to follow by ear.
        text = said + (f"\nเลขพัสดุ {order['tracking']}" if order["tracking"] else "")
        quick = ["ใช่", "ไม่ใช่"] if s.step else ["ติดตามคำสั่งซื้ออื่น", "แจ้งไม่ได้รับสินค้า", "จบการสนทนา"]
        return Reply(text, quick, "order_status",
                     speech=speech_text(said, config.SAY_AS, keep_together=(config.BRAND,)))

    def _is_late(self, order: dict) -> bool:
        status = order["status"]
        return bool(order["eta"]) and order["eta"] < self._today() and not (
            status.startswith("จัดส่งสำเร็จ") or "ยกเลิก" in status)

    def _order_action(self, s: Session, purpose: str, order_id: str, order: dict, said: str) -> Reply:
        """What the customer asked for, once the order is known. Changes go to a person as a ticket
        or a handoff: the bot itself never cancels or edits an order."""
        status = order["status"]
        delivered, cancelled = status.startswith("จัดส่งสำเร็จ"), "ยกเลิก" in status
        if purpose == "order_cancel":
            if cancelled:
                return Reply(f"คำสั่งซื้อ {order_id} ยกเลิกแล้ว{P}", config.MAIN_MENU, "order_cancel")
            if status in config.CANCELLABLE_ORDER_STATUSES:
                return self._offer_ticket(
                    s, f"คำสั่งซื้อ {order_id} ยังไม่ได้จัดส่ง{P} ส่งคำขอยกเลิกให้เจ้าหน้าที่ดำเนินการไหม{Q}",
                    "order_cancel", f"ขอยกเลิกคำสั่งซื้อ {order_id}", order_id)
            return Reply(f"คำสั่งซื้อ {order_id} สถานะ{status} จึงยกเลิกไม่ได้แล้ว{P} "
                         f"ถ้าไม่ต้องการสินค้า ขอคืนสินค้าได้หลังได้รับ{P} {config.RETURN_POLICY_TEXT}",
                         ["ขอคืนสินค้า", "คุยกับเจ้าหน้าที่"], "order_cancel")
        if purpose == "order_change_address":
            if delivered or cancelled:
                return Reply(f"คำสั่งซื้อ {order_id} {status} จึงเปลี่ยนที่อยู่จัดส่งไม่ได้{P}",
                             config.MAIN_MENU, "order_change_address")
            return self._handoff(s, "order_change_address",
                                 lead=f"การเปลี่ยนที่อยู่จัดส่งต้องให้เจ้าหน้าที่ดำเนินการ{P}")
        if purpose == "order_not_received" and delivered:
            when = f"เมื่อวันที่ {thai_date(order['eta'])}" if order["eta"] else ""
            return self._offer_ticket(
                s, f"ระบบแสดงว่าคำสั่งซื้อ {order_id} จัดส่งสำเร็จ{when}{P} "
                   f"ให้เปิดเรื่องให้เจ้าหน้าที่ตรวจสอบกับขนส่งไหม{Q}",
                "order_not_received", f"แจ้งไม่ได้รับสินค้า คำสั่งซื้อ {order_id}", order_id)
        if purpose == "order_return":
            if not delivered:
                return Reply(f"คำสั่งซื้อ {order_id} {status} ยังไม่ได้รับสินค้า{P} "
                             f"ถ้าได้รับแล้วมีปัญหา แจ้งคืนสินค้าได้{P}", config.MAIN_MENU, "order_return")
            return self._offer_ticket(
                s, f"{config.RETURN_POLICY_TEXT} ให้เปิดเรื่องคืนหรือเปลี่ยนสินค้าคำสั่งซื้อ {order_id} ไหม{Q}",
                "order_return", f"ขอคืน/เปลี่ยนสินค้า คำสั่งซื้อ {order_id}", order_id, detail=said or None)
        return self._order_status_reply(s, order_id, order)   # status, late, not received yet

    def _step_need_problem(self, s: Session, message: str) -> Optional[Reply]:
        if len(compact(message)) < 4:
            return None
        if self._topic not in (None, "report_problem", "greeting", "thanks"):
            return None  # "ขอใบเสร็จ", "ยกเลิกออเดอร์"...: another request, not the problem
        s.slots["problem"], s.step = strip_particles(normalize(message)), "confirm_problem"
        return Reply(f"สรุปว่า {s.slots['problem']} ใช่ไหม{Q}", ["ใช่", "ไม่ใช่"], s.flow)

    def _step_confirm_problem(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if answer is None:
            return None
        if not answer:
            s.step = "need_problem"
            return self._ask(s)
        s.slots.update(category="report_problem", description=s.slots["problem"], order_id=None)
        return self._create_ticket(s)

    # ---- tickets: offer, ask for a number to call back, create, look up --------------------
    def _set_offer(self, s: Session, category: str, description: str, order_id: Optional[str] = None,
                   detail: Optional[str] = None):
        """`description` becomes the case's short_description; `detail` (the customer's words) its description."""
        s.flow, s.step, s.retries = "offer_ticket", "confirm_ticket", 0
        s.slots = {"category": category, "description": description, "order_id": order_id, "detail": detail}

    def _offer_ticket(self, s: Session, text: str, category: str, description: str,
                      order_id: Optional[str] = None, detail: Optional[str] = None) -> Reply:
        self._set_offer(s, category, description, order_id, detail)
        return Reply(text, ["ใช่", "ไม่ใช่"], category)

    def _step_confirm_ticket(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if answer is None:
            return None
        if not answer:
            s.leave_flow()
            return Reply(f"ได้{P} มีอะไรให้ช่วยอีกไหม{Q}", config.MAIN_MENU, "declined")
        return self._create_ticket(s)

    def _create_ticket(self, s: Session) -> Reply:
        """Open the case in s.slots. Without a verified phone, first ask where to call back."""
        if not (s.verified_phone or s.slots.get("callback")):
            s.flow, s.step, s.retries = s.flow or "offer_ticket", "need_callback", 0
            return self._ask(s)
        try:
            ticket = backend.create_case(s.slots["description"], s.slots["category"], consumer=s.verified_phone,
                                         callback_phone=s.slots.get("callback"), order_id=s.slots.get("order_id"),
                                         contact_type=s.channel, description=s.slots.get("detail"))
        except backend.CaseError:
            return self._handoff(s, "case_error", lead=f"ขออภัย{P} ระบบบันทึกเรื่องขัดข้อง")
        s.leave_flow()
        s.context["ticket"] = ticket
        return Reply(f"รับเรื่องแล้ว{P} เลขที่เรื่อง {ticket} {config.CALLBACK_PROMISE}{P} "
                     f"ถ้าต้องการตามเรื่อง บอกว่า เช็คเรื่อง {ticket} ได้เลย{P}",
                     ["เช็คยอดค้างชำระ", "จบการสนทนา"], "ticket_created")

    def _step_need_callback(self, s: Session, message: str) -> Optional[Reply]:
        m = PHONE.search(digits_only(message))
        if not m:
            return None
        s.slots["callback"] = m.group()
        return self._create_ticket(s)

    def _step_need_ticket(self, s: Session, message: str) -> Optional[Reply]:
        m = TICKET_NO.search(message) or CASE_DIGITS.search(digits_only(message))
        if not m:
            return None
        number = db.case_number(m.group(1))           # "1001" -> CS0001001
        try:
            case = backend.get_case(number)
        except backend.CaseError:
            return self._handoff(s, "case_error", lead=f"ขออภัย{P} ตอนนี้ตรวจสอบเรื่องไม่ได้")
        if not case:
            s.retries += 1
            return Reply(f"ไม่พบเรื่องเลขที่ {number} {P} ขอเลขอีกครั้งได้ไหม{Q}",
                         ["คุยกับเจ้าหน้าที่", "ยกเลิก"], s.flow)
        s.leave_flow()
        s.context["ticket"] = number
        when = f" แจ้งเมื่อวันที่ {thai_date(case['created'])}" if case["created"] else ""
        text = f"เรื่อง {number}{when} สถานะ {case['status']}{P}"
        if case["done"]:
            return Reply(text, config.MAIN_MENU + ["จบการสนทนา"], "ticket_status")
        if case["state"] == config.CASE_AWAITING_INFO:   # proactive: the agent is waiting for the customer
            s.flow, s.step, s.slots = "ticket_status", "confirm_next", {"yes": "agent"}
            return Reply(text + f" ให้โอนไปให้ข้อมูลกับเจ้าหน้าที่เลยไหม{Q}", ["ใช่", "ไม่ใช่"], "ticket_status")
        return Reply(text + f" ถ้าต้องการให้เร่งเรื่อง ให้เจ้าหน้าที่ช่วยดูได้{P}",
                     ["คุยกับเจ้าหน้าที่", "จบการสนทนา"], "ticket_status")

    def _finish(self, s: Session) -> Reply:
        """Identity confirmed: complete the task the customer came for."""
        flow = s.flow
        s.leave_flow()
        if flow == "check_balance":
            return self._balance(s)
        return Reply(f"ยืนยันตัวตนแล้ว{P} มีอะไรให้ช่วย{Q}", config.MAIN_MENU)

    def _balance(self, s: Session) -> Reply:
        c = backend.find_customer(s.verified_phone)
        if c["balance"] <= 0:
            return Reply(f"คุณ{c['name']} ไม่มียอดค้างชำระ{P}", config.MAIN_MENU + ["จบการสนทนา"], "check_balance")
        text = f"คุณ{c['name']} มียอดค้างชำระ {baht(c['balance'])} "
        if c["due"] and c["due"] < self._today():
            text += f"ครบกำหนดวันที่ {thai_date(c['due'])} ซึ่งเลยกำหนดแล้ว{P}"
        else:
            text += f"ครบกำหนดวันที่ {thai_date(c['due'])}{P}" if c["due"] else P
        # Proactive: the usual next question, asked aloud so it also works on the phone.
        s.flow, s.step, s.slots = "check_balance", "confirm_next", {"yes": "payment_channels"}
        return Reply(text + f" ต้องการทราบช่องทางชำระเงินไหม{Q}",
                     ["ช่องทางชำระเงิน", "จ่ายแล้วแต่ยอดยังไม่ลด", "จบการสนทนา"], "check_balance")

    def _step_confirm_next(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if answer is None:
            return None
        topic = s.slots.get("yes")
        s.leave_flow()
        if answer and topic:
            return getattr(self, f"_on_{topic}")(s, message)
        return Reply(f"ได้{P} มีอะไรให้ช่วยอีกไหม{Q}", config.MAIN_MENU + ["จบการสนทนา"], "declined")

    def _today(self):
        return self.clock().date()

    def _agents_open(self) -> bool:
        if not config.AGENT_HOURS:
            return True
        now = self.clock()
        opens, closes = config.AGENT_HOURS.get(now.weekday(), (0, 0))
        return opens <= now.hour < closes

    # ---- topics -------------------------------------------------------------------------
    def _on_greeting(self, s, message):
        return self.welcome()

    def _on_check_balance(self, s, message):
        if s.verified_phone:
            return self._balance(s)
        s.flow, s.step, s.slots, s.retries = "check_balance", "need_phone", {}, 0
        return self._step_need_phone(s, message) or self._ask(s)

    def _on_order_status(self, s, message, flow="order_status"):
        s.flow, s.step, s.retries = flow, "need_order", 0
        s.slots = {"said": strip_particles(normalize(message))}
        return self._step_need_order(s, message) or self._ask(s)

    def _on_order_cancel(self, s, message):
        return self._on_order_status(s, message, "order_cancel")

    def _on_order_change_address(self, s, message):
        return self._on_order_status(s, message, "order_change_address")

    def _on_order_late(self, s, message):
        return self._on_order_status(s, message, "order_late")

    def _on_order_not_received(self, s, message):
        return self._on_order_status(s, message, "order_not_received")

    def _on_order_return(self, s, message):
        return self._on_order_status(s, message, "order_return")

    def _on_ticket_status(self, s, message):
        s.flow, s.step, s.slots, s.retries = "ticket_status", "need_ticket", {}, 0
        return self._step_need_ticket(s, message) or self._ask(s)

    def _on_faq(self, s, message, entry):
        """An answer from the faq table; its action may offer a ticket or hand over."""
        if entry["action"] == "handoff":
            return self._handoff(s, entry["topic"], lead=entry["answer"])
        if entry["action"] == "offer_ticket":
            return self._offer_ticket(
                s, f"{entry['answer']} ต้องการให้เปิดเรื่องให้เจ้าหน้าที่ดำเนินการไหม{Q}",
                entry["topic"], entry["title"], s.context.get("order"), detail=strip_particles(normalize(message)))
        return Reply(entry["answer"], config.MAIN_MENU + ["จบการสนทนา"], entry["topic"])

    def _on_report_problem(self, s, message):
        s.flow, s.step, s.slots, s.retries = "report_problem", "need_problem", {}, 0
        # "เน็ตหลุดบ่อยตั้งแต่เมื่อวาน" already describes the problem; "แจ้งปัญหา" alone does not.
        if len(compact(message)) >= 15:
            return self._step_need_problem(s, message)
        return self._ask(s)

    def _on_payment_channels(self, s, message):
        *first, last = config.PAYMENT_CHANNELS
        return Reply(f"ชำระได้ทาง{' '.join(first)} หรือ{last}{P}",
                     ["เช็คยอดค้างชำระ", "จบการสนทนา"], "payment_channels")

    def _on_hours(self, s, message):
        now = "ขณะนี้อยู่ในเวลาทำการ" if self._agents_open() else "ขณะนี้อยู่นอกเวลาทำการ"
        return Reply(f"เจ้าหน้าที่ให้บริการ{config.HOURS_TEXT}{P} {now}{P}",
                     config.MAIN_MENU, "hours")

    def _on_thanks(self, s, message):
        return Reply(f"ยินดี{P} มีอะไรให้ช่วยอีกไหม{Q}", config.MAIN_MENU + ["จบการสนทนา"], "thanks")

    def _on_goodbye(self, s, message):
        return Reply(f"ขอบคุณที่ติดต่อนะ{Q} สวัสดี{P}", [], "goodbye", end=True)

    def _on_agent(self, s, message):
        return self._handoff(s)

    def _handoff(self, s: Session, reason: str = "agent", lead: str = "") -> Reply:
        """Pass the customer to a person; `reason` becomes the channel's handoffReason.
        Outside agent hours, offer a call back instead of a queue nobody answers."""
        s.leave_flow()
        lead = f"{lead} " if lead else ""
        if not self._agents_open() and reason != "case_error":   # cannot open a case: hand over anyway
            return self._offer_ticket(
                s, f"{lead}ขณะนี้อยู่นอกเวลาทำการ{P} เจ้าหน้าที่ให้บริการ{config.HOURS_TEXT} "
                   f"ให้เปิดเรื่องให้เจ้าหน้าที่ติดต่อกลับไหม{Q}",
                "callback", f"ขอให้ติดต่อกลับ ({reason})", s.context.get("order"))
        return Reply(f"{lead}กำลังโอนให้เจ้าหน้าที่ รอสักครู่นะ{Q}", [], reason, handoff=True,
                     context=dict(s.context))

    def _not_understood(self, s: Session, message: str) -> Reply:
        if self.fallback:
            text = self.fallback(message, s)
            if text:
                s.misunderstood = 0
                return Reply(text, config.MAIN_MENU, "fallback")
        s.misunderstood += 1
        if s.misunderstood >= config.MAX_MISUNDERSTOOD:
            return Reply(f"ขออภัย{P} ยังไม่เข้าใจ ให้เจ้าหน้าที่ช่วยไหม{Q}",
                         ["คุยกับเจ้าหน้าที่"] + config.MAIN_MENU[:3], "not_understood")
        return Reply(f"ขออภัย{P} ช่วยบอกอีกครั้งได้ไหม{Q}",
                     config.MAIN_MENU, "not_understood")

    def _expire_old_sessions(self):
        cutoff = time.time() - self.session_ttl
        for sid in [sid for sid, s in self.sessions.items() if s.last_active < cutoff]:
            del self.sessions[sid]
