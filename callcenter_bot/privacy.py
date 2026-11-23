"""Hide personal numbers before text leaves the bot (logs, AI requests). PDPA."""
import re


def mask_digits(text: str) -> str:
    """Phone/ID/account numbers (7+ digits, even when split with spaces or dashes) keep only
    their last 4 digits; a lone 4-digit number (the ID-card check) is hidden completely.
    Order numbers (6 digits) stay readable."""
    def mask(m):
        n = sum(ch.isdigit() for ch in m.group())
        if n == 4 and m.group().isdigit():
            return "xxxx"
        if n < 7:
            return m.group()
        seen, out = 0, []
        for ch in m.group():
            if ch.isdigit():
                seen += 1
                out.append(ch if seen > n - 4 else "x")
            else:
                out.append(ch)
        return "".join(out)
    return re.sub(r"\d[\d\s\-]*\d", mask, text)
