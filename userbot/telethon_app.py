"""Telethon glue: connects to YOUR account and hands events to the Engine. Run: python -m userbot.telethon_app"""
import asyncio
import io
import logging
import os
import sys
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from . import web
from .ai import GroqClient
from .engine import Engine, Incoming
from .store import Store

MARK = "\u200b"          # invisible marker on messages the bot puts in Saved Messages
log = logging.getLogger("userbot")


class TelethonIO:
    def __init__(self, client):
        self.client = client

    async def send(self, chat_id, text):
        for _ in range(2):
            try:
                return (await self.client.send_message(chat_id, text)).id
            except FloodWaitError as e:                       # Telegram asked us to slow down: obey
                log.warning("FloodWait %ss", e.seconds)
                await asyncio.sleep(min(e.seconds + 1, 90))
        return None

    async def notify(self, text):
        return (await self.client.send_message("me", MARK + text[:3900])).id

    async def typing(self, chat_id, seconds):
        try:
            async with self.client.action(chat_id, "typing"):
                await asyncio.sleep(seconds)
        except Exception:
            await asyncio.sleep(seconds)

    async def delete(self, chat_id, msg_id):
        try:
            await self.client.delete_messages(chat_id, msg_id)
        except Exception:
            pass

    async def resolve(self, ref):
        try:
            ref = int(ref) if ref.lstrip("-").isdigit() else ref
            ent = await self.client.get_entity(ref)
            return ent.id, display_name(ent)
        except Exception:
            return None

    # ---- reactions & stories (raw API; needs a recent Telethon) ----
    async def react(self, chat_id, msg_id, emoji):
        try:
            from telethon.tl.functions.messages import SendReactionRequest
            from telethon.tl.types import ReactionEmoji
            await self.client(SendReactionRequest(peer=await self.client.get_input_entity(chat_id), msg_id=msg_id, reaction=[ReactionEmoji(emoticon=emoji)]))
            return True
        except Exception as e:
            log.info("reaction failed: %s", type(e).__name__)
            return False

    async def view_story(self, peer_id, story_id):
        try:
            from telethon.tl.functions.stories import IncrementStoryViewsRequest, ReadStoriesRequest
            peer = await self.client.get_input_entity(peer_id)
            await self.client(IncrementStoryViewsRequest(peer=peer, id=[story_id]))
            await self.client(ReadStoriesRequest(peer=peer, max_id=story_id))
            return True
        except Exception as e:
            log.info("story view failed: %s", type(e).__name__)
            return False

    async def react_story(self, peer_id, story_id, emoji):
        try:
            from telethon.tl.functions.stories import SendReactionRequest as StoryReaction
            from telethon.tl.types import ReactionEmoji
            await self.client(StoryReaction(peer=await self.client.get_input_entity(peer_id), story_id=story_id, reaction=ReactionEmoji(emoticon=emoji)))
            return True
        except Exception as e:
            log.info("story reaction failed: %s", type(e).__name__)
            return False

    # ---- reading / files ----
    async def recent_own(self, chat_id, n):
        try:
            return [m.raw_text async for m in self.client.iter_messages(chat_id, from_user="me", limit=n) if m.raw_text]
        except Exception:
            return []

    async def chat_history(self, chat_id, n):
        try:
            rows = [m async for m in self.client.iter_messages(chat_id, limit=n) if m.raw_text]
            return [f"{'Me' if m.out else 'Them'}: {m.raw_text}" for m in reversed(rows)]
        except Exception:
            return []

    async def schedule(self, chat_id, text, ts):
        try:
            await self.client.send_message(chat_id, text, schedule=datetime.fromtimestamp(ts, timezone.utc))
            return True
        except Exception as e:
            log.info("schedule failed: %s", type(e).__name__)
            return False

    async def send_file_saved(self, name, data):
        bio = io.BytesIO(data)
        bio.name = name
        await self.client.send_file("me", bio, force_document=True, caption=MARK + "🗄 " + name)

    async def read_file(self, msg_id):
        try:
            msg = await self.client.get_messages("me", ids=msg_id)
            return await msg.download_media(file=bytes) if msg and msg.file else None
        except Exception:
            return None

    async def report_spam(self, chat_id):
        try:
            from telethon.tl.functions.messages import ReportSpamRequest
            await self.client(ReportSpamRequest(peer=await self.client.get_input_entity(chat_id)))
        except Exception:
            pass

    async def fetch_page(self, url):
        try:
            return await web.fetch_text(url)
        except Exception:
            return None

    async def send_voice(self, chat_id, wav):
        try:
            bio = io.BytesIO(wav)
            bio.name = "voice.wav"
            await self.client.send_file(chat_id, bio, voice_note=True)
            return True
        except Exception:
            return False


REQUIRED = ("TG_API_ID", "TG_API_HASH", "TG_SESSION", "GROQ_API_KEY")


def normalize_session(raw):
    """Clean a pasted session string (spaces, line breaks, missing '=' padding). Returns (string or None, problem or None)."""
    import base64
    s = "".join((raw or "").split())
    if not s:
        return None, "TG_SESSION is empty"
    if s[0] != "1":
        return None, "TG_SESSION must start with the digit 1 (it is the long string printed by login.py - not the API hash or a phone number)"
    body = s[1:]
    body += "=" * (-len(body) % 4)
    try:
        n = len(base64.urlsafe_b64decode(body))
    except Exception:
        return None, f"TG_SESSION is not valid ({len(s)} characters). It was probably cut off or has extra characters. Run login.py again and copy the WHOLE string"
    if n not in (263, 275):
        return None, f"TG_SESSION looks incomplete: {len(s)} characters, expected about 353. Run login.py again and copy the WHOLE string"
    return "1" + body, None


def read_config(environ):
    """Returns (config dict, list of problems). Values are trimmed and stray quotes removed."""
    clean = {k: (environ.get(k) or "").strip().strip("\"'").strip() for k in (*REQUIRED, "DATABASE_URL", "DB_PATH")}
    problems = [f"{k} is empty or missing" for k in REQUIRED if not clean[k]]
    if clean["TG_SESSION"]:
        fixed, why = normalize_session(clean["TG_SESSION"])
        if why:
            problems.append(why)
        else:
            clean["TG_SESSION"] = fixed
    if clean["TG_API_ID"] and not clean["TG_API_ID"].isdigit():
        problems.append("TG_API_ID must be only digits (the number from my.telegram.org)")
    return clean, problems


def display_name(user):
    return " ".join(x for x in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if x) or getattr(user, "username", None) or str(user.id)


async def health_server():
    """Tiny HTTP endpoint so hosts that need a web port (Render web service) are happy, and an uptime pinger can keep it awake."""
    async def handle(reader, writer):
        try:
            await asyncio.wait_for(reader.read(1024), 5)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
    port = int(os.environ.get("PORT", "0") or 0)
    if port:
        await asyncio.start_server(handle, "0.0.0.0", port)
        log.info("Health endpoint listening on port %s (/health)", port)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    await health_server()                                  # up immediately, so the host sees a healthy service
    cfg, problems = read_config(os.environ)
    if problems:
        log.error("Setup problem:\n  - " + "\n  - ".join(problems) +
                  "\nOn Render: open your service > Environment, fill in these values, then Save, rebuild and deploy."
                  "\nTG_SESSION comes from running login.py on your own phone/computer (see README).")
        sys.exit(1)
    api_id, api_hash, session = int(cfg["TG_API_ID"]), cfg["TG_API_HASH"], cfg["TG_SESSION"]
    if not cfg["DATABASE_URL"] and not cfg["DB_PATH"]:
        log.warning("No DATABASE_URL set: settings are kept in a local file and will reset when this host redeploys.")
    os.environ["GROQ_API_KEY"] = cfg["GROQ_API_KEY"]
    store = Store(cfg["DB_PATH"] or "userbot.db", url=cfg["DATABASE_URL"] or None)
    await asyncio.to_thread(store.wait_for_leadership, 5, log.info)   # never run two copies on one Telegram session
    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("The session is no longer valid. Run login.py again.")
    me = await client.get_me()
    engine = Engine(store, TelethonIO(client), GroqClient(), owner_name=me.first_name or "the owner")
    log.info("Personal assistant running for %s (id %s). Mode: %s", display_name(me), me.id, engine.s.get("mode"))

    @client.on(events.NewMessage(incoming=True))
    async def on_incoming(event):
        try:
            if event.message.action or (event.is_channel and not event.is_group):
                return
            if not (event.is_private or event.is_group):
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False) or sender.id == me.id:
                return
            reply_to_me = False
            if event.is_group and event.is_reply:
                r = await event.get_reply_message()
                reply_to_me = bool(r and r.sender_id == me.id)
            name = display_name(sender)
            chat_name = name if event.is_private else (getattr(await event.get_chat(), "title", None) or name)
            await engine.on_incoming(Incoming(
                chat_id=event.chat_id, sender_id=sender.id, name=name, chat_name=chat_name, text=event.raw_text or "",
                has_voice=bool(event.voice), has_photo=bool(event.photo), msg_id=event.id, is_group=bool(event.is_group),
                mentioned=bool(event.message.mentioned), reply_to_me=reply_to_me, is_contact=bool(getattr(sender, "contact", False)),
                get_media=lambda e=event: e.download_media(file=bytes)))
        except Exception:
            log.exception("incoming handler failed")

    @client.on(events.NewMessage(outgoing=True))
    async def on_outgoing(event):
        try:
            text = event.raw_text or ""
            if event.chat_id == me.id:                          # Saved Messages: commands and draft decisions
                if text.startswith(MARK) or (event.file and not text):
                    return                                      # our own notification / file
                await engine.on_saved(text, event.reply_to_msg_id)
            elif event.is_private or (event.is_group and text.startswith(".ai")):
                chat = await event.get_chat()
                reply_text = None
                if text.startswith(".ai") and event.is_reply:
                    r = await event.get_reply_message()
                    reply_text = r.raw_text if r else None
                name = display_name(chat) if event.is_private else (getattr(chat, "title", None) or str(event.chat_id))
                await engine.on_outgoing(event.chat_id, name, text, event.id, event.reply_to_msg_id, reply_text)
        except Exception:
            log.exception("outgoing handler failed")

    # ---- stories: live updates, plus a safety-net poll ----
    try:
        from telethon.tl.types import PeerUser, UpdateStory

        async def handle_story(peer_id, story):
            if story.__class__.__name__ != "StoryItem" or getattr(story, "out", False):
                return
            try:
                ent = await client.get_entity(peer_id)
                await engine.on_story(peer_id, story.id, display_name(ent), bool(getattr(ent, "contact", False)))
            except Exception:
                log.exception("story handler failed")

        @client.on(events.Raw(UpdateStory))
        async def on_story(update):
            if isinstance(update.peer, PeerUser):
                await handle_story(update.peer.user_id, update.story)

        async def poll_stories():
            from telethon.tl.functions.stories import GetAllStoriesRequest
            res = await client(GetAllStoriesRequest())
            for ps in getattr(res, "peer_stories", []) or []:
                if isinstance(ps.peer, PeerUser):
                    for st in ps.stories:
                        await handle_story(ps.peer.user_id, st)
    except Exception:
        log.warning("Stories need a newer Telethon (pip install -U telethon); story features are disabled.")

        async def poll_stories():
            return None

    async def alert_outside(text):
        """Tell you through a normal bot if Saved Messages is unreachable (needs ALERT_BOT_TOKEN + ALERT_CHAT_ID)."""
        token, chat = os.environ.get("ALERT_BOT_TOKEN", ""), os.environ.get("ALERT_CHAT_ID", "")
        if token and chat:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15) as c:
                    await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text})
            except Exception:
                pass

    async def background():
        n, last_ok = 0, True
        while True:
            await asyncio.sleep(60)
            n += 1
            try:
                await engine.tick()
                if n % 10 == 0 and engine.s.get("stories") != "off":
                    await poll_stories()
                if n % 5 == 0:                                    # session health check
                    await client.get_me()
                    if not last_ok:
                        await engine.io.notify("✅ Connection restored.")
                    last_ok = True
            except Exception as e:
                log.exception("background task failed")
                if last_ok and n % 5 == 0:
                    last_ok = False
                    msg = f"⚠️ Your personal assistant has a connection problem: {type(e).__name__}. If it says AuthKey/Unauthorized, run login.py again."
                    try:
                        await engine.io.notify(msg)
                    except Exception:
                        await alert_outside(msg)

    asyncio.create_task(background())
    await engine.io.notify("🤖 Personal assistant is online. Mode: " + engine.s.get("mode") + ". Send .ai help here for commands.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
