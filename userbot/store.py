"""State store: SQLite file (default) or Postgres (set DATABASE_URL, e.g. your Neon database).
Tables are prefixed ub_ so they can share a database with other projects."""
import sqlite3
import time

DEFAULTS = {
    "mode": "draft",          # off | draft | auto
    "disclose": "1",          # first auto-reply says it comes from an assistant
    "allow_all": "0",         # 0 = only chats you allowed with ".ai on"
    "instructions": "", "faq": "", "away": "",
    "hours_start": "", "hours_end": "",   # your working hours: the bot answers OUTSIDE them
    "tz": "3", "daily_limit": "50",
    "panic": "0", "prev_mode": "draft",
    "react": "off", "react_mode": "lite", "react_prob": "0.4", "react_limit": "40",
    "stories": "off", "story_emoji": "❤️", "story_limit": "30", "story_all": "0",
    "urgent": "1", "scam": "1", "spam": "0", "payments": "0", "booking": "0", "voice": "0",
    "away_until": "0", "away_msg": "", "dnd_start": "", "dnd_end": "", "digest_hour": "21", "styles": "{}",
}

def _schema(pg):
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    BIG, REAL = ("BIGINT", "DOUBLE PRECISION") if pg else ("INTEGER", "REAL")
    return f"""
CREATE TABLE IF NOT EXISTS ub_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ub_chats (chat_id {BIG} PRIMARY KEY, name TEXT, allowed INTEGER DEFAULT 0,
    paused_until {REAL} DEFAULT 0, disclosed INTEGER DEFAULT 0, away_sent {REAL} DEFAULT 0, memory TEXT DEFAULT '', msg_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ub_msgs (id {ID}, chat_id {BIG}, role TEXT, content TEXT, ts {REAL});
CREATE TABLE IF NOT EXISTS ub_drafts (msg_id {BIG} PRIMARY KEY, chat_id {BIG}, text TEXT);
CREATE TABLE IF NOT EXISTS ub_usage (day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (day, kind));
CREATE TABLE IF NOT EXISTS ub_reminders (id {ID}, due {REAL}, text TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ub_followups (id {ID}, chat_id {BIG}, created {REAL}, due {REAL}, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ub_birthdays (chat_id {BIG} PRIMARY KEY, name TEXT, month INTEGER, day INTEGER);
CREATE TABLE IF NOT EXISTS ub_templates (name TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ub_later (id {ID}, url TEXT, note TEXT, ts {REAL});
CREATE TABLE IF NOT EXISTS ub_payments (id {ID}, chat_id {BIG}, code TEXT, amount {REAL}, direction TEXT, party TEXT, ts {REAL});
CREATE TABLE IF NOT EXISTS ub_appts (id {ID}, chat_id {BIG}, name TEXT, when_ts {REAL}, note TEXT, reminded INTEGER DEFAULT 0, status TEXT DEFAULT 'booked');
CREATE TABLE IF NOT EXISTS ub_seen_stories (peer_id {BIG}, story_id INTEGER, PRIMARY KEY (peer_id, story_id));
"""


NEW_CHAT_COLUMNS = {"vip": "INTEGER DEFAULT 0", "style": "TEXT DEFAULT ''", "notes": "TEXT DEFAULT ''", "story": "INTEGER DEFAULT 0",
                    "is_group": "INTEGER DEFAULT 0", "last_in": "REAL DEFAULT 0", "last_out": "REAL DEFAULT 0"}
CHAT_FIELDS = {"name", "allowed", "paused_until", "disclosed", "away_sent", "memory", "msg_count", *NEW_CHAT_COLUMNS}
LOCK_KEY = 84729113      # Postgres advisory lock: only one running copy may be connected to your Telegram account


class Store:
    def __init__(self, path=":memory:", url=None):
        self.pg = bool(url)
        self.url = url
        self.lock_conn = None
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.db = psycopg.connect(url, row_factory=dict_row, autocommit=True)
            self.db.execute(_schema(True))
            for col, ddl in NEW_CHAT_COLUMNS.items():
                self.db.execute(f"ALTER TABLE ub_chats ADD COLUMN IF NOT EXISTS {col} {ddl.replace('REAL', 'DOUBLE PRECISION')}")
        else:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(_schema(False))
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(ub_chats)")}
            for col, ddl in NEW_CHAT_COLUMNS.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE ub_chats ADD COLUMN {col} {ddl}")
            self.db.commit()

    # ---- plumbing ----
    def _x(self, sql, args=()):
        if self.pg:
            return self.db.execute(sql.replace("?", "%s"), args)
        cur = self.db.execute(sql, args)
        self.db.commit()
        return cur

    def _one(self, sql, args=()):
        r = self._x(sql, args).fetchone()
        return dict(r) if r else None

    def _all(self, sql, args=()):
        return [dict(r) for r in self._x(sql, args).fetchall()]

    def wait_for_leadership(self, poll=5, log=print):
        """Postgres only. Blocks until no other copy of the assistant is running (e.g. during a zero-downtime redeploy).
        Two copies using one Telegram session would make Telegram revoke it."""
        if not self.pg:
            return
        import psycopg
        self.lock_conn = psycopg.connect(self.url, autocommit=True)
        waited = False
        while True:
            if self.lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]:
                return
            if not waited:
                log("Another copy of the assistant is running; waiting for it to stop...")
                waited = True
            time.sleep(poll)

    # ---- settings ----
    def get(self, key):
        r = self._one("SELECT value FROM ub_settings WHERE key=?", (key,))
        return r["value"] if r else DEFAULTS.get(key, "")

    def set(self, key, value):
        self._x("INSERT INTO ub_settings (key, value) VALUES (?,?) ON CONFLICT (key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # ---- chats ----
    def chat(self, chat_id, name=None):
        self._x("INSERT INTO ub_chats (chat_id, name) VALUES (?,?) ON CONFLICT (chat_id) DO NOTHING", (chat_id, name))
        if name:
            self._x("UPDATE ub_chats SET name=? WHERE chat_id=?", (name, chat_id))
        return self._one("SELECT * FROM ub_chats WHERE chat_id=?", (chat_id,))

    def update_chat(self, chat_id, **fields):
        assert set(fields) <= CHAT_FIELDS
        if fields:
            self.chat(chat_id)
            sets = ", ".join(f"{k}=?" for k in fields)
            self._x(f"UPDATE ub_chats SET {sets} WHERE chat_id=?", (*fields.values(), chat_id))

    def allowed_chats(self):
        return self._all("SELECT * FROM ub_chats WHERE allowed=1 ORDER BY name")

    def forget_chat(self, chat_id):
        self._x("DELETE FROM ub_msgs WHERE chat_id=?", (chat_id,))
        self._x("UPDATE ub_chats SET memory='', msg_count=0, disclosed=0, away_sent=0 WHERE chat_id=?", (chat_id,))

    # ---- messages ----
    def add_msg(self, chat_id, role, content):
        self._x("INSERT INTO ub_msgs (chat_id, role, content, ts) VALUES (?,?,?,?)", (chat_id, role, content[:4000], time.time()))
        self._x("DELETE FROM ub_msgs WHERE ts < ?", (time.time() - 30 * 86400,))     # keep 30 days only

    def history(self, chat_id, limit=12):
        rows = self._all("SELECT role, content FROM ub_msgs WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit))
        return [{"role": "user" if r["role"] == "them" else "assistant", "content": r["content"]} for r in reversed(rows)]

    def bot_replies_last_hour(self, chat_id):
        return self._one("SELECT count(*) AS n FROM ub_msgs WHERE chat_id=? AND role='bot' AND ts > ?", (chat_id, time.time() - 3600))["n"]

    # ---- drafts ----
    def add_draft(self, msg_id, chat_id, text):
        self._x("INSERT INTO ub_drafts (msg_id, chat_id, text) VALUES (?,?,?) ON CONFLICT (msg_id) DO UPDATE SET chat_id=excluded.chat_id, text=excluded.text",
                (msg_id, chat_id, text))

    def get_draft(self, msg_id):
        return self._one("SELECT * FROM ub_drafts WHERE msg_id=?", (msg_id,))

    def del_draft(self, msg_id):
        self._x("DELETE FROM ub_drafts WHERE msg_id=?", (msg_id,))

    # ---- usage ----
    def used_today(self, kind="reply"):
        r = self._one("SELECT n FROM ub_usage WHERE day=? AND kind=?", (time.strftime("%Y-%m-%d", time.gmtime()), kind))
        return r["n"] if r else 0

    def log_use(self, kind="reply"):
        self._x("INSERT INTO ub_usage (day, kind, n) VALUES (?,?,1) ON CONFLICT (day, kind) DO UPDATE SET n = ub_usage.n + 1",
                (time.strftime("%Y-%m-%d", time.gmtime()), kind))


    # ================= v2 =================
    def recent_owner_msgs(self, n=8):
        rows = self._all("SELECT content FROM ub_msgs WHERE role='owner' ORDER BY id DESC LIMIT ?", (n,))
        return [r["content"] for r in reversed(rows)]

    def count_today(self, kind):
        return self.used_today(kind)

    def top_chats_today(self, limit=5):
        midnight = time.time() - (time.time() % 86400)
        return self._all("SELECT c.name AS name, count(*) AS n FROM ub_msgs m JOIN ub_chats c ON c.chat_id=m.chat_id "
                         "WHERE m.role='them' AND m.ts >= ? GROUP BY c.chat_id, c.name ORDER BY n DESC LIMIT ?", (midnight, limit))

    def unanswered(self, since, limit=8):
        return self._all("SELECT chat_id, name, last_in FROM ub_chats WHERE allowed=1 AND last_in > ? AND last_in > last_out ORDER BY last_in DESC LIMIT ?", (since, limit))

    def them_since(self, chat_id, since, limit=6):
        rows = self._all("SELECT content FROM ub_msgs WHERE chat_id=? AND role='them' AND ts > ? ORDER BY id DESC LIMIT ?", (chat_id, since, limit))
        return [r["content"] for r in reversed(rows)]

    def pending_drafts(self):
        return self._one("SELECT count(*) AS n FROM ub_drafts")["n"]

    # reminders / follow-ups
    def add_reminder(self, due, text):
        self._x("INSERT INTO ub_reminders (due, text) VALUES (?,?)", (due, text))

    def due_reminders(self, now):
        rows = self._all("SELECT * FROM ub_reminders WHERE done=0 AND due <= ? ORDER BY due", (now,))
        for r in rows:
            self._x("UPDATE ub_reminders SET done=1 WHERE id=?", (r["id"],))
        return rows

    def add_followup(self, chat_id, created, due):
        self._x("INSERT INTO ub_followups (chat_id, created, due) VALUES (?,?,?)", (chat_id, created, due))

    def due_followups(self, now):
        rows = self._all("SELECT * FROM ub_followups WHERE done=0 AND due <= ?", (now,))
        for r in rows:
            self._x("UPDATE ub_followups SET done=1 WHERE id=?", (r["id"],))
        return rows

    # birthdays / templates / later / payments / appointments / stories
    def set_birthday(self, chat_id, name, month, day):
        self._x("INSERT INTO ub_birthdays (chat_id, name, month, day) VALUES (?,?,?,?) ON CONFLICT (chat_id) DO UPDATE SET name=excluded.name, month=excluded.month, day=excluded.day",
                (chat_id, name, month, day))

    def birthdays(self, month=None, day=None):
        if month:
            return self._all("SELECT * FROM ub_birthdays WHERE month=? AND day=?", (month, day))
        return self._all("SELECT * FROM ub_birthdays ORDER BY month, day")

    def del_birthday(self, chat_id):
        return self._x("DELETE FROM ub_birthdays WHERE chat_id=?", (chat_id,)).rowcount

    def set_template(self, name, text):
        self._x("INSERT INTO ub_templates (name, text) VALUES (?,?) ON CONFLICT (name) DO UPDATE SET text=excluded.text", (name, text))

    def get_template(self, name):
        r = self._one("SELECT text FROM ub_templates WHERE name=?", (name,))
        return r["text"] if r else None

    def templates(self):
        return self._all("SELECT * FROM ub_templates ORDER BY name")

    def del_template(self, name):
        return self._x("DELETE FROM ub_templates WHERE name=?", (name,)).rowcount

    def add_later(self, url, note):
        self._x("INSERT INTO ub_later (url, note, ts) VALUES (?,?,?)", (url, note[:200], time.time()))

    def later(self, limit=10):
        return self._all("SELECT * FROM ub_later ORDER BY id DESC LIMIT ?", (limit,))

    def clear_later(self):
        self._x("DELETE FROM ub_later")

    def add_payment(self, chat_id, p):
        if self._one("SELECT 1 AS x FROM ub_payments WHERE code=?", (p["code"],)):
            return False
        self._x("INSERT INTO ub_payments (chat_id, code, amount, direction, party, ts) VALUES (?,?,?,?,?,?)",
                (chat_id, p["code"], p["amount"], p["direction"], p["party"], time.time()))
        return True

    def payments(self, since):
        return self._all("SELECT * FROM ub_payments WHERE ts >= ? ORDER BY ts DESC", (since,))

    def add_appt(self, chat_id, name, when_ts, note):
        self._x("INSERT INTO ub_appts (chat_id, name, when_ts, note) VALUES (?,?,?,?)", (chat_id, name, when_ts, note))
        return self._one("SELECT max(id) AS id FROM ub_appts")["id"]

    def appt_conflict(self, when_ts):
        return bool(self._one("SELECT 1 AS x FROM ub_appts WHERE status='booked' AND when_ts BETWEEN ? AND ?", (when_ts - 1740, when_ts + 1740)))

    def appts(self, now):
        return self._all("SELECT * FROM ub_appts WHERE status='booked' AND when_ts > ? ORDER BY when_ts LIMIT 15", (now - 3600,))

    def cancel_appt(self, aid):
        r = self._one("SELECT * FROM ub_appts WHERE id=? AND status='booked'", (aid,))
        if r:
            self._x("UPDATE ub_appts SET status='cancelled' WHERE id=?", (aid,))
        return r

    def due_appt_reminders(self, now):
        rows = self._all("SELECT * FROM ub_appts WHERE status='booked' AND reminded=0 AND when_ts > ? AND when_ts <= ?", (now, now + 3600))
        for r in rows:
            self._x("UPDATE ub_appts SET reminded=1 WHERE id=?", (r["id"],))
        return rows

    def story_seen(self, peer_id, story_id):
        return bool(self._one("SELECT 1 AS x FROM ub_seen_stories WHERE peer_id=? AND story_id=?", (peer_id, story_id)))

    def mark_story(self, peer_id, story_id):
        self._x("INSERT INTO ub_seen_stories (peer_id, story_id) VALUES (?,?) ON CONFLICT (peer_id, story_id) DO NOTHING", (peer_id, story_id))

    # backup / restore
    def export_all(self):
        import json
        return json.dumps({"settings": {k: self.get(k) for k in DEFAULTS},
                           "chats": [r for r in self._all("SELECT chat_id, name, allowed, vip, style, notes, story, memory FROM ub_chats WHERE allowed=1 OR vip=1 OR story=1")],
                           "templates": self.templates(), "birthdays": self.birthdays()}, ensure_ascii=False, indent=1)

    def import_all(self, raw):
        import json
        d = json.loads(raw)
        for k, v in (d.get("settings") or {}).items():
            if k in DEFAULTS and k not in ("panic",):
                self.set(k, v)
        for c in d.get("chats") or []:
            cid = c.pop("chat_id")
            self.update_chat(cid, **{k: v for k, v in c.items() if k in CHAT_FIELDS})
        for t in d.get("templates") or []:
            self.set_template(t["name"], t["text"])
        for b in d.get("birthdays") or []:
            self.set_birthday(b["chat_id"], b["name"], b["month"], b["day"])
        return len(d.get("chats") or [])
