"""AI fallback tests with a fake client: no network, no API key, no cost."""
import unittest
from types import SimpleNamespace

from callcenter_bot import Bot

try:
    import anthropic
    from callcenter_bot.ai_fallback import make_claude_fallback
except ImportError:  # the AI extra is optional
    anthropic = None


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])


class FakeClient:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@unittest.skipIf(anthropic is None, "pip install -r requirements-ai.txt")
class AIFallbackTest(unittest.TestCase):
    def bot_with(self, result):
        client = FakeClient(result)
        return Bot(fallback=make_claude_fallback(client=client)), client

    def test_answers_what_rules_do_not_cover(self):
        bot, client = self.bot_with(text_response("สมัครสมาชิกได้ที่หน้าเว็บไซต์ค่ะ"))
        r = bot.reply("s", "สมัครสมาชิกยังไง")
        self.assertEqual((r.text, r.intent), ("สมัครสมาชิกได้ที่หน้าเว็บไซต์ค่ะ", "fallback"))
        self.assertEqual(client.calls[0]["model"], "claude-opus-5-5")

    def test_rules_still_handle_sensitive_flows(self):
        bot, client = self.bot_with(text_response("ไม่ควรถูกเรียก"))
        r = bot.reply("s", "เช็คยอดค้างชำระ")
        self.assertEqual(r.intent, "check_balance")
        self.assertEqual(client.calls, [])

    def test_history_sent_with_numbers_masked(self):
        bot, client = self.bot_with(text_response("ได้ค่ะ"))
        bot.reply("s", "เช็คยอด 0812345678")
        bot.reply("s", "1234")
        bot.reply("s", "ต้องใช้เอกสารอะไรบ้าง")
        sent = str(client.calls[0]["messages"])
        self.assertNotIn("0812345678", sent)
        self.assertNotIn("'1234'", sent)
        self.assertIn("xxxxxx5678", sent)
        self.assertEqual(client.calls[0]["messages"][-1],
                         {"role": "user", "content": "ต้องใช้เอกสารอะไรบ้าง"})
        roles = [m["role"] for m in client.calls[0]["messages"]]
        self.assertEqual(roles, ["user", "assistant"] * 2 + ["user"])

    def test_refusal_falls_back_to_rules_message(self):
        bot, _ = self.bot_with(text_response("", stop_reason="refusal"))
        r = bot.reply("s", "อะไรสักอย่าง")
        self.assertEqual(r.intent, "not_understood")

    def test_api_failure_falls_back_to_rules_message(self):
        bot, _ = self.bot_with(anthropic.APIConnectionError(message="down", request=None))
        r = bot.reply("s", "อะไรสักอย่าง")
        self.assertEqual(r.intent, "not_understood")

    def test_unexpected_error_never_breaks_the_chat(self):
        bot, _ = self.bot_with(TypeError("no credentials"))
        with self.assertLogs("ai_fallback", "ERROR"):
            r = bot.reply("s", "อะไรสักอย่าง")
        self.assertEqual(r.intent, "not_understood")


if __name__ == "__main__":
    unittest.main()
