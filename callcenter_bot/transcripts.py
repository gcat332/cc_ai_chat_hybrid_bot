"""What happened with the bot, for the people who take over: a short summary and the transcript.

Both go back to Genesys on handoff (Data Action / Audio Connector outputs) for Set Participant Data;
Genesys keeps at most 500 characters per participant attribute, so both are cut to fit. Genesys
(OpenFrame) then carries them to ServiceNow: this server does not write to ServiceNow itself.

Personal numbers are already masked in the bot's history (privacy.mask_digits).
"""
GENESYS_LIMIT = 500   # characters per participant attribute (Set Participant Data)


def transcript(session) -> str:
    """The conversation as lines: "ลูกค้า: ..." / "บอท: ..."."""
    return "\n".join(f"{'ลูกค้า' if who == 'user' else 'บอท'}: {text}" for who, text in session.history)


def summary(session, request: str = "") -> str:
    """One line for the agent: who, how they were verified, what they want, what they asked."""
    from .bot import TOPIC_NAMES, REQUESTS     # here, to keep the import graph one-way
    parts = []
    if session.verified_id:
        parts.append(f"ยืนยันตัวตนแล้ว ({session.verified_by})")
    else:
        parts.append("ยังไม่ยืนยันตัวตน")
    if request:
        parts.append(f"ต้องการ: {request}")
    if session.context.get("reason"):
        parts.append(f"เหตุผล: {session.context['reason']}")
    if session.context.get("loan"):
        parts.append(f"สินเชื่อ: {session.context['loan']}")
    asked = [TOPIC_NAMES.get(t) or REQUESTS.get(t) for t in session.topics]
    asked = [a for a in asked if a and a not in request]
    if asked:
        parts.append("ถามเรื่อง: " + ", ".join(asked))
    return fit(" | ".join(parts))


# Participant data ServiceNow reads from the call (KTB PayOff PoC, BR "MFEC Genesys - fetch participant
# data"): names are case-sensitive. All strings, "" when unknown. With topic=payoff, verifiedPhone and a
# caller whose number is the ServiceNow consumer's, ServiceNow runs its PayOff flow.
PARTICIPANT_FIELDS = ("topic", "identify_type", "kyc_result", "loan_number", "reason", "closing_within_days",
                      "new_bank_name", "new_interest_rate", "promotion_period_months", "cashback_offered")
OFFER_FIELDS = ("closing_within_days", "new_bank_name", "new_interest_rate", "promotion_period_months",
                "cashback_offered")
PAYOFF = ("loan_close", "loan_refinance", "loan_not_active")
KYC_FAILED = ("verify_failed", "verify_locked")


def topic(intent: str) -> str:
    """ServiceNow's topic for what the call was about: payoff, homeloan_inquiry, credit_card, deposit,
    complaint, other."""
    intent = intent or ""
    if intent in PAYOFF:
        return "payoff"
    if intent.startswith(("loan", "mortgage", "home_insurance", "tax_certificate", "prepayment")):
        return "homeloan_inquiry"
    if intent.startswith(("card", "cash_advance")) or intent == "balance_due":
        return "credit_card"
    if intent.startswith(("deposit", "account", "atm", "transfer", "withdraw", "debit", "promptpay")) \
            or intent in ("transaction_help", "bank_certificate", "auto_debit"):
        return "deposit"
    if intent in ("complaint", "unauthorized"):
        return "complaint"
    return "other"


def participant_data(session, handoff_reason: str = "") -> dict:
    """The PARTICIPANT_FIELDS for this call, as strings."""
    ctx = session.context
    about = handoff_reason if topic(handoff_reason) != "other" or not session.topics else session.topics[-1]
    if ctx.get("reason_code") or ctx.get("loan_no") and handoff_reason in PAYOFF:
        about = handoff_reason
    data = dict.fromkeys(PARTICIPANT_FIELDS, "")
    data.update(
        topic=topic(about),
        identify_type="national_id" if session.verified_id else "",
        kyc_result="pass" if session.verified_id else "fail" if handoff_reason in KYC_FAILED else "",
        loan_number=ctx.get("loan_no", ""),
        reason=ctx.get("reason_code", ""),
        **{k: str(v) for k, v in (ctx.get("offer") or {}).items() if k in OFFER_FIELDS})
    return data


def fit(text: str, limit: int = GENESYS_LIMIT) -> str:
    """Cut to `limit` characters, keeping the end (the latest lines matter most)."""
    return text if len(text) <= limit else "…" + text[-(limit - 1):]
