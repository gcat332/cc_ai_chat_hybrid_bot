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
from typing import Callable, Optional

from . import backend, config
from .intents import detect, is_cancel, yes_no
from .normalize import compact, digits_only, normalize, strip_particles
from .privacy import mask_digits
from .thai_format import baht, mask_phone, speech_text, thai_date

P, Q, ME = config.STATEMENT_PARTICLE, config.QUESTION_PARTICLE, config.SELF

PHONE = re.compile(r"(?<!\d)0\d{8,9}(?!\d)")
ID_LAST4 = re.compile(r"(?<!\d)\d{4}(?!\d)")
ORDER_ID = re.compile(r"(?<!\d)\d{6}(?!\d)")


@dataclass
class Reply:
    text: str
    quick_replies: list = field(default_factory=list)
    intent: Optional[str] = None
    handoff: bool = False  # the channel should pass the customer to a human agent
    end: bool = False  # the conversation is over
    expects: Optional[str] = None  # "digits": the bot is waiting for a number (show a keypad)
    speech: str = ""  # the same reply worded for text-to-speech (numbers read digit by digit)

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
                 session_ttl: int = 30 * 60):
        """`fallback(message, session)` may return a reply for lines no rule understood,
        e.g. from an LLM or an FAQ search. Leave it None for rules only."""
        self.fallback = fallback
        self.session_ttl = session_ttl
        self.sessions = {}
        self._lock = threading.Lock()

    # ---- public -------------------------------------------------------------------------
    def reply(self, session_id: str, message: str) -> Reply:
        with self._lock:
            self._expire_old_sessions()
            s = self.sessions.setdefault(session_id, Session())
            s.last_active = time.time()
            reply = self._reply(s, session_id, message)
            if s.step in ("need_phone", "need_id4", "need_order"):
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

        intent, _ = detect(message)
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

        handler = getattr(self, f"_on_{intent}", None) if intent else None
        if handler:
            s.misunderstood = 0
            reply = handler(s, message)
            if reply.end:
                self.sessions.pop(session_id, None)
            return reply
        return self._not_understood(s, message)

    def _continue_flow(self, s: Session, message: str, intent: Optional[str]) -> Optional[Reply]:
        step_handler = getattr(self, f"_step_{s.step}")
        reply = step_handler(s, message)
        if reply:
            return reply
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
        s.leave_flow()
        delivered = order["status"].startswith("จัดส่งสำเร็จ")
        said = f"คำสั่งซื้อ {m.group()} {order['status']}"
        if delivered and order["eta"]:
            said += f"เมื่อวันที่ {thai_date(order['eta'])}"
        elif order["carrier"]:
            said += f"โดย {order['carrier']}"
        said += P if "\u0e00" <= said[-1] <= "\u0e7f" else f" {P}"   # "...Express ค่ะ", "...สินค้าค่ะ"
        if order["eta"] and not delivered:
            said += f" คาดว่าจะได้รับวันที่ {thai_date(order['eta'])}{P}"
        # The tracking number is shown, not read out: a long code is hard to follow by ear.
        text = said + (f"\nเลขพัสดุ {order['tracking']}" if order["tracking"] else "")
        return Reply(text, ["ติดตามคำสั่งซื้ออื่น", "แจ้งปัญหา", "จบการสนทนา"], "order_status",
                     speech=speech_text(said, config.SAY_AS, keep_together=(config.BRAND,)))

    def _step_need_problem(self, s: Session, message: str) -> Optional[Reply]:
        if len(compact(message)) < 4:
            return None
        s.slots["problem"], s.step = strip_particles(normalize(message)), "confirm_problem"
        return Reply(f"สรุปว่า {s.slots['problem']} ใช่ไหม{Q}", ["ใช่", "ไม่ใช่"], s.flow)

    def _step_confirm_problem(self, s: Session, message: str) -> Optional[Reply]:
        answer = yes_no(message)
        if answer is None:
            return None
        if not answer:
            s.step = "need_problem"
            return self._ask(s)
        ticket = backend.create_ticket(s.verified_phone, s.slots["problem"])
        s.leave_flow()
        return Reply(f"รับเรื่องแล้ว{P} เลขที่เรื่อง {ticket} เจ้าหน้าที่จะติดต่อกลับภายใน 24 ชั่วโมง{P}",
                     ["เช็คยอดค้างชำระ", "จบการสนทนา"], "ticket_created")

    def _finish(self, s: Session) -> Reply:
        """Identity confirmed: complete the task the customer came for."""
        flow = s.flow
        s.leave_flow()
        if flow == "check_balance":
            return self._balance(s)
        return Reply(f"ยืนยันตัวตนแล้ว{P} มีอะไรให้ช่วย{Q}", config.MAIN_MENU)

    def _balance(self, s: Session) -> Reply:
        c = backend.find_customer(s.verified_phone)
        if c["balance"] > 0:
            text = f"คุณ{c['name']} มียอดค้างชำระ {baht(c['balance'])} "
            text += f"ครบกำหนดวันที่ {thai_date(c['due'])}{P}" if c["due"] else P
        else:
            text = f"คุณ{c['name']} ไม่มียอดค้างชำระ{P}"
        return Reply(text, ["ช่องทางชำระเงิน", "แจ้งปัญหา", "จบการสนทนา"], "check_balance")

    # ---- topics -------------------------------------------------------------------------
    def _on_greeting(self, s, message):
        return self.welcome()

    def _on_check_balance(self, s, message):
        if s.verified_phone:
            return self._balance(s)
        s.flow, s.step, s.slots, s.retries = "check_balance", "need_phone", {}, 0
        return self._step_need_phone(s, message) or self._ask(s)

    def _on_order_status(self, s, message):
        s.flow, s.step, s.slots, s.retries = "order_status", "need_order", {}, 0
        return self._step_need_order(s, message) or self._ask(s)

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
        return Reply(f"เจ้าหน้าที่ให้บริการ{config.HOURS_TEXT}{P}",
                     config.MAIN_MENU, "hours")

    def _on_thanks(self, s, message):
        return Reply(f"ยินดี{P} มีอะไรให้ช่วยอีกไหม{Q}", config.MAIN_MENU + ["จบการสนทนา"], "thanks")

    def _on_goodbye(self, s, message):
        return Reply(f"ขอบคุณที่ติดต่อนะ{Q} สวัสดี{P}", [], "goodbye", end=True)

    def _on_agent(self, s, message):
        return self._handoff(s)

    def _handoff(self, s: Session) -> Reply:
        s.leave_flow()
        return Reply(f"กำลังโอนให้เจ้าหน้าที่ รอสักครู่นะ{Q}", [], "agent", handoff=True)

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
