# Personal assistant for your own Telegram account (no Premium / Business needed)

This logs in as **you** (Telegram's user API, via Telethon) and can draft or send replies in your private chats.
It is separate from your bots. It must run on an always-on machine: a PC, a Raspberry Pi, a small server, or your Android phone with Termux.
Do **not** run it on Vercel/serverless (no always-on process): your account would log in from changing IP addresses, which Telegram treats as suspicious.

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

### Render – free Web Service (what `render.yaml` sets up)
1. Do steps 1-3 above on your own phone/computer to get `TG_SESSION` (never run `login.py` on the server).
2. Push this folder to a **private** GitHub repo.
3. Render → **New → Blueprint** → pick the repo. Enter `DATABASE_URL` (your Neon connection string; the tables start with `ub_`),
   `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`, `GROQ_API_KEY`. Deploy.
4. Open the service's **Logs**: "Personal assistant running" and a message in your Saved Messages.
5. **Keep it awake:** a free web service sleeps after ~15 minutes without web traffic, which would disconnect you.
   Create a free monitor (UptimeRobot or cron-job.org) that opens `https://YOUR-SERVICE.onrender.com/health` **every 5 minutes**.
   (A single free service uses about 744 of the 750 free hours per month; check Render's current free-tier terms.)
Safety built in: the assistant takes a database lock before connecting, so during a redeploy the new copy waits until the old one has stopped
(two copies on one session would make Telegram revoke it). Never run a second copy elsewhere with the same `TG_SESSION`.

### Render – paid Background Worker with a disk
Rename `render-worker.yaml` to `render.yaml`. No database or pinger needed; the worker never sleeps and the disk keeps SQLite.

### Always-on hosting
The included `Dockerfile` / `Procfile` work on Railway, Render, Fly.io or any VPS. Put the four variables in the host's secret settings and keep `DB_PATH` on a persistent volume.

## Using it
Everything is controlled from **Saved Messages** with commands starting `.ai`. Send `.ai help` for topics:
`core`, `safety`, `react`, `tools`, `organise`. Inside any chat you can also type commands (the message disappears and the answer goes to Saved Messages).

**What it can do**
- **Replies** (draft = you approve, or auto), per-chat **styles**, an FAQ, your **tone** learned from your own messages, short **memory** per person, **voice notes and photos** understood, **groups** (only when mentioned/replied to).
- **Safety:** `.ai panic` kill switch, VIP list (never auto-replied, always alerts you), sensitive topics (money, PINs, passwords, codes) always handed to you, **urgent** and **scam** alerts (keyword-based, no AI, work in every private chat), optional **spam reporting**.
- **Reactions:** `.ai react on` reacts to some messages in allowed chats (keyword or AI-picked emoji, limits per day); `.ai react ❤️` reacts on demand to the message you reply to.
- **Stories:** `.ai stories view|react` views (and reacts to) stories from people you allow (`.ai story allow @name`), or all contacts (`.ai story all on`). Human-like delays and a daily limit. Needs a recent Telethon (`pip install -U telethon`).
- **Away & quiet hours:** `.ai away until 2d <message>`, `.ai dnd 22 7`, working hours.
- **Tools:** `.ai sum`, `.ai tr fr`, `.ai write <idea>`, templates (`.ai t price`), read-later (`.ai later`), M-Pesa confirmation log (`.ai payments on`), scheduled messages (`.ai send 2h @mum text`).
- **Organise:** reminders, follow-ups ("remind me if they don't reply"), birthdays with a drafted greeting, a daily **digest**, `.ai recap` (who is waiting for you), appointment **booking** with conflict checks and reminders, backup/restore.
- **Health:** it checks your session every few minutes and tells you in Saved Messages (and, if you set `ALERT_BOT_TOKEN` + `ALERT_CHAT_ID`, through a normal bot) if something is wrong.

**Drafts** arrive in Saved Messages: reply to a draft with `ok`, `skip`, or your own text. If you type in a chat yourself, the assistant stays quiet there for 30 minutes.

Tests (no login needed): `python tests/test_engine.py && python tests/test_v2.py && python tests/test_glue.py` (the last one runs the Telegram wiring against a fake Telethon).
