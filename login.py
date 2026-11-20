"""Run this ONCE on your own phone/computer to create your session string.
You will be asked for your phone number, the code Telegram sends you, and your 2-step password (if any).
Never share the printed string with anyone: it gives full access to your account."""
import os

from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(os.environ.get("TG_API_ID") or input("API ID (from my.telegram.org): ").strip())
api_hash = os.environ.get("TG_API_HASH") or input("API hash: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    me = client.get_me()
    print(f"\nLogged in as {me.first_name} (id {me.id}).")
    print("\nYour TG_SESSION (secret!):\n")
    print(client.session.save())
    print("\nPut it in the TG_SESSION environment variable of the server that runs the bot.")
