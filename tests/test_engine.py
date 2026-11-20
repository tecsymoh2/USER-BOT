import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from userbot.engine import Engine, Incoming, parse_duration
from userbot.store import Store


class FakeIO:
    def __init__(self): self.sent, self.notes, self.deleted, self.typing_calls, self.n = [], [], [], [], 100
    async def send(self, chat_id, text): self.sent.append((chat_id, text)); return 1
    async def notify(self, text): self.n += 1; self.notes.append((self.n, text)); return self.n
    async def typing(self, chat_id, seconds): self.typing_calls.append(seconds)
    async def delete(self, chat_id, msg_id): self.deleted.append((chat_id, msg_id))
    async def resolve(self, ref): return (777, "Dan") if ref in ("@dan", "777") else None


class FakeAI:
    def __init__(self): self.replies, self.systems = [], []
    async def chat(self, system, messages, max_tokens=400, temperature=0.5, model=None):
        self.systems.append(system); return self.replies.pop(0) if self.replies else "ok then"
    async def vision(self, system, history, prompt, image): self.systems.append(system); return "Nice photo!"
    async def transcribe(self, audio): return "what time do you open?"


T = [1_800_000_000.0]
def make():
    io, ai = FakeIO(), FakeAI()
    e = Engine(Store(), io, ai, owner_name="Ola", now=lambda: T[0], sleep=lambda s: asyncio.sleep(0), rand=lambda a, b: a)
    return e, io, ai
def inc(text="hi", chat=500, name="Cathy", **kw): return Incoming(chat_id=chat, sender_id=chat, name=name, text=text, **kw)
def run(c): return asyncio.run(c)


# 1. not allowed -> silent; ".ai on" inside the chat allows it and deletes the command
e, io, ai = make(); e.s.set("mode", "auto")
run(e.on_incoming(inc())); assert not io.sent and not io.notes
run(e.on_outgoing(500, "Cathy", ".ai on", 42)); assert (500, 42) in io.deleted and "handle Cathy" in io.notes[-1][1]
ai.replies.append("Hello Cathy!"); run(e.on_incoming(inc())); assert io.sent and "Auto-reply from Ola" in io.sent[-1][1]
print("allowlist ok")

# 2. disclosure only first time; typing delay used; our own message does not pause the chat
ai.replies.append("Second."); io.sent.clear(); run(e.on_incoming(inc("again")))
assert io.sent[-1][1] == "Second." and io.typing_calls
run(e.on_outgoing(500, "Cathy", "Second.", 43)); assert e.s.chat(500)["paused_until"] == 0
print("disclosure + own-message ok")

# 3. manual typing pauses 30 min, then resumes
run(e.on_outgoing(500, "Cathy", "I'll handle this myself", 44)); assert e.s.chat(500)["paused_until"] > T[0]
io.sent.clear(); run(e.on_incoming(inc("hello??"))); assert not io.sent
T[0] += 31 * 60; ai.replies.append("Back!"); run(e.on_incoming(inc("hello again"))); assert io.sent[-1][1] == "Back!"
print("pause ok")

# 4. draft mode -> notification with draft, then ok / custom / skip
e, io, ai = make(); run(e.command("allow @dan")); e.s.update_chat(500, allowed=1)
ai.replies.append("We open at 9."); run(e.on_incoming(inc("when do you open?")))
mid, text = io.notes[-1]; assert "Draft for Cathy" in text and "We open at 9." in text and not io.sent
run(e.on_saved("ok", mid)); assert io.sent[-1] == (500, "We open at 9.") and io.notes[-1][1] == "✅ Sent."
ai.replies.append("Maybe."); run(e.on_incoming(inc("price?"))); mid = io.notes[-1][0]
run(e.on_saved("It's 500 shillings", mid)); assert io.sent[-1] == (500, "It's 500 shillings")
ai.replies.append("x"); run(e.on_incoming(inc("another"))); mid = io.notes[-1][0]; n = len(io.sent)
run(e.on_saved("skip", mid)); assert len(io.sent) == n and e.s.get_draft(mid) is None
print("drafts ok")

# 5. working hours silent + away message once
e, io, ai = make(); e.s.set("mode", "auto"); e.s.update_chat(500, allowed=1); e.s.set("disclose", "0")
h = e.local_now().hour
e.s.set("hours_start", h); e.s.set("hours_end", min(h + 2, 24)); ai.replies.append("hi"); run(e.on_incoming(inc())); assert not io.sent; ai.replies.clear()
e.s.set("hours_start", (h + 5) % 24); e.s.set("hours_end", (h + 7) % 24 if (h + 7) % 24 > (h + 5) % 24 else 24); e.s.set("away", "Closed now, back at 9.")
assert not e.in_working_hours(); ai.replies.append("Sure!"); run(e.on_incoming(inc("anyone?"))); assert io.sent[-1][1].startswith("Closed now, back at 9.") and "Sure!" in io.sent[-1][1]
ai.replies.append("Yes."); run(e.on_incoming(inc("hello?"))); assert "Closed now" not in io.sent[-1][1]
print("hours + away ok")

# 6. daily limit and per-hour limit
e, io, ai = make(); e.s.set("mode", "auto"); e.s.update_chat(500, allowed=1); e.s.set("disclose", "0"); e.s.set("daily_limit", "2")
for i in range(4): ai.replies.append(f"r{i}"); run(e.on_incoming(inc(f"m{i}")))
assert len(io.sent) == 2
e, io, ai = make(); e.s.set("mode", "auto"); e.s.update_chat(500, allowed=1); e.s.set("daily_limit", "500")
for i in range(9): ai.replies.append(f"r{i}"); run(e.on_incoming(inc(f"m{i}")))
assert len(io.sent) == 6
print("limits ok")

# 7. ESCALATE and NO_REPLY
e, io, ai = make(); e.s.set("mode", "auto"); e.s.update_chat(500, allowed=1)
ai.replies.append("ESCALATE"); run(e.on_incoming(inc("Can I get a refund?"))); assert not io.sent and "needs you" in io.notes[-1][1]
ai.replies.append("NO_REPLY"); run(e.on_incoming(inc("ok thanks"))); assert not io.sent
print("escalate ok")

# 8. voice + photo + memory every 5 messages + FAQ/instructions in the prompt
e, io, ai = make(); e.s.set("mode", "auto"); e.s.update_chat(500, allowed=1); e.s.set("disclose", "0")
async def media(): return b"x"
e.s.set("faq", "Open 9-6. Haircut KSh 500."); e.s.set("instructions", "I run a salon.")
ai.replies.append("We open at 9."); run(e.on_incoming(inc("", has_voice=True, get_media=media))); assert io.sent[-1][1] == "We open at 9." and "Haircut KSh 500" in ai.systems[-1] and "salon" in ai.systems[-1]
run(e.on_incoming(inc("", has_photo=True, get_media=media))); assert io.sent[-1][1] == "Nice photo!"
for i in range(2): ai.replies.append("ok"); run(e.on_incoming(inc(f"x{i}")))
ai.replies.append("fine"); ai.replies.append("Name: Cathy. Likes braids."); run(e.on_incoming(inc("5th")))
assert e.s.chat(500)["memory"] == "Name: Cathy. Likes braids."; ai.replies.append("hey"); run(e.on_incoming(inc("next"))); assert "Name: Cathy" in ai.systems[-1]
print("media + memory ok")

# 9. commands
e, io, ai = make()
assert "mode off|draft|auto" in run(e.command("help")); assert "Mode: draft" in run(e.command("status"))
assert "auto" in run(e.command("mode auto")) and e.s.get("mode") == "auto"; assert "Usage" in run(e.command("mode loud"))
assert "EVERY" in run(e.command("allowall on")) and e.s.get("allow_all") == "1"; run(e.command("allowall off"))
assert "Allowed: Dan" in run(e.command("allow @dan")) and "Dan" in run(e.command("allowed")); assert "Removed" in run(e.command("deny 777"))
assert "couldn't find" in run(e.command("allow @nobody"))
run(e.command("prompt Be brief")); assert e.s.get("instructions") == "Be brief"; run(e.command("prompt reset")); assert e.s.get("instructions") == ""
assert "Working hours 9:00" in run(e.command("hours 9 18")) and "No working hours" in run(e.command("hours off")); assert "Usage" in run(e.command("hours 99 1"))
run(e.command("limit 10")); assert e.s.get("daily_limit") == "10"; run(e.command("tz +3")); assert e.s.get("tz") == "3"
run(e.on_saved(".ai mode off")); assert e.s.get("mode") == "off" and "Mode: off" in io.notes[-1][1]
assert parse_duration("2h") == 7200 and parse_duration("30m") == 1800 and parse_duration("x") is None
assert "Paused" in run(e.chat_command(500, "Cathy", "pause 2h")) and e.s.chat(500)["paused_until"] > T[0]
assert "Resumed" in run(e.chat_command(500, "Cathy", "resume")); assert "Forgot" in run(e.chat_command(500, "Cathy", "forget"))
print("commands ok")

# 10. mode off ignores everyone
e, io, ai = make(); e.s.set("mode", "off"); e.s.update_chat(500, allowed=1); run(e.on_incoming(inc())); assert not io.sent and not io.notes
print("ALL USERBOT TESTS PASSED")
