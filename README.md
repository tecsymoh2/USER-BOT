# Personal assistant for your own Telegram account (no Premium / Business needed)

This logs in as **you** (Telegram's user API, via Telethon) and can draft or send replies in your private chats.
It is separate from your bots. It must run on an always-on machine: a PC, a Raspberry Pi, a small server, or your Android phone with Termux.
Do **not** run it on Vercel/serverless: your account would log in from changing IP addresses, which Telegram treats as suspicious.

## ⚠️ Read this first
- The session string created by `login.py` is **full access to your account** (all chats, can send as you). Keep it only in the environment of the machine that runs the bot. Never send it to anyone, never commit it, never paste it into a chat (including with an AI).
- If it leaks: Telegram → Settings → Devices → terminate that session.
- Safe defaults: **draft mode** (you approve every reply), **only chats you allow**, short replies with human-like delays, a daily limit and an hourly per-chat limit.
  Telegram can limit accounts that send lots of automated messages. Don't use this for mass messaging.
- Tell people they are talking to an assistant if they might care: `disclose` is on by default for auto mode.

## Setup (10 minutes)
1. Go to https://my.telegram.org → *API development tools* → create an app → copy **api_id** and **api_hash**.
2. Get a free Groq key at https://console.groq.com.
3. Install Python 3.10+ and run:
   ```
   pip install -r requirements.txt
   export TG_API_ID=123456 TG_API_HASH=abcdef...      # Windows: set instead of export
   python login.py          # phone number, the code Telegram sends you, 2-step password if you have one
   ```
   Copy the printed string.
4. Start the assistant:
   ```
   export TG_API_ID=... TG_API_HASH=... TG_SESSION="<the string>" GROQ_API_KEY=...
   python -m userbot.telethon_app
   ```
   You'll get a message in **Saved Messages**: "Personal assistant is online".

### Android (Termux)
```
pkg update && pkg install python git
pip install telethon httpx
termux-wake-lock
```
then the same steps 3-4. It only runs while the phone keeps Termux alive.

### Render
1. Do steps 1-3 above on your own phone/computer to get `TG_SESSION` (never run `login.py` on the server).
2. Push this folder to a **private** GitHub repo.
3. Render → **New → Blueprint** → choose the repo. It creates a **Background Worker** with a small persistent disk (from `render.yaml`).
   Enter `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `GROQ_API_KEY` when asked, then deploy.
4. Open the worker's **Logs**: you should see "Personal assistant running", and a message appears in your Saved Messages.
Notes: use a *Background Worker* (a free Web Service sleeps and would disconnect you), keep the disk (without it the settings reset on every deploy),
and run only **one** copy: two copies using the same session will make Telegram invalidate it.

### Always-on hosting
The included `Dockerfile` / `Procfile` work on Railway, Render, Fly.io or any VPS. Put the four variables in the host's secret settings and keep `DB_PATH` on a persistent volume.

## Using it
Everything is controlled from **Saved Messages** with commands starting `.ai` (send `.ai help`):
- `.ai allow @username` (or type `.ai on` inside that chat; the command message disappears)
- `.ai mode draft|auto|off` · `.ai prompt <how to reply>` · `.ai faq <prices, hours, policies>`
- `.ai hours 9 18` (you handle chats 9-18, it answers outside) · `.ai away <message>` · `.ai limit 30` · `.ai tz +3`
- In a chat: `.ai pause 2h` · `.ai resume` · `.ai forget` · `.ai memory`

**Drafts** arrive in Saved Messages: reply to a draft with `ok` to send it, `skip`, or type your own text to send that instead.
If you type in a chat yourself, the assistant stays quiet there for 30 minutes. It also understands voice notes and photos, remembers short notes per person,
and hands anything it can't answer to you (it tells you in Saved Messages and does not reply).

Tests (no login needed): `python tests/test_engine.py`
