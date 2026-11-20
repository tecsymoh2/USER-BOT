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
}

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ub_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ub_chats (chat_id INTEGER PRIMARY KEY, name TEXT, allowed INTEGER DEFAULT 0,
    paused_until REAL DEFAULT 0, disclosed INTEGER DEFAULT 0, away_sent REAL DEFAULT 0, memory TEXT DEFAULT '', msg_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ub_msgs (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, role TEXT, content TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS ub_drafts (msg_id INTEGER PRIMARY KEY, chat_id INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS ub_usage (day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (day, kind));
"""
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS ub_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ub_chats (chat_id BIGINT PRIMARY KEY, name TEXT, allowed INTEGER DEFAULT 0,
    paused_until DOUBLE PRECISION DEFAULT 0, disclosed INTEGER DEFAULT 0, away_sent DOUBLE PRECISION DEFAULT 0, memory TEXT DEFAULT '', msg_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ub_msgs (id BIGSERIAL PRIMARY KEY, chat_id BIGINT, role TEXT, content TEXT, ts DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS idx_ub_msgs_chat ON ub_msgs(chat_id, id);
CREATE TABLE IF NOT EXISTS ub_drafts (msg_id BIGINT PRIMARY KEY, chat_id BIGINT, text TEXT);
CREATE TABLE IF NOT EXISTS ub_usage (day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (day, kind));
"""
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
            self.db.execute(PG_SCHEMA)
        else:
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.executescript(SQLITE_SCHEMA)

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
        assert set(fields) <= {"name", "allowed", "paused_until", "disclosed", "away_sent", "memory", "msg_count"}
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
