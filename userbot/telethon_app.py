"""Telethon glue: connects to YOUR account and hands events to the Engine. Run: python -m userbot.telethon_app"""
import asyncio
import logging
import os
import sys

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

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
            name = " ".join(x for x in (getattr(ent, "first_name", None), getattr(ent, "last_name", None)) if x) or getattr(ent, "title", None) or str(ent.id)
            return ent.id, name
        except Exception:
            return None


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
    try:
        api_id, api_hash, session = int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"], os.environ["TG_SESSION"]
    except KeyError as e:
        sys.exit(f"Missing environment variable {e}. See .env.example")
    store = Store(os.environ.get("DB_PATH", "userbot.db"), url=os.environ.get("DATABASE_URL"))
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
            if not event.is_private or event.message.action:
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False) or sender.id == me.id:
                return
            await engine.on_incoming(Incoming(
                chat_id=event.chat_id, sender_id=sender.id, name=display_name(sender), text=event.raw_text or "",
                has_voice=bool(event.voice), has_photo=bool(event.photo), msg_id=event.id,
                get_media=lambda e=event: e.download_media(file=bytes)))
        except Exception:
            log.exception("incoming handler failed")

    @client.on(events.NewMessage(outgoing=True))
    async def on_outgoing(event):
        try:
            text = event.raw_text or ""
            if event.chat_id == me.id:                          # Saved Messages: commands and draft decisions
                if text.startswith(MARK):
                    return                                      # our own notification
                await engine.on_saved(text, event.reply_to_msg_id)
            elif event.is_private:
                chat = await event.get_chat()
                await engine.on_outgoing(event.chat_id, display_name(chat), text, event.id)
        except Exception:
            log.exception("outgoing handler failed")

    await engine.io.notify("🤖 Personal assistant is online. Mode: " + engine.s.get("mode") + ". Send .ai help here for commands.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
