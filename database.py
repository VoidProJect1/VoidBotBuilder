"""⚡ Void Bot Builder — Database Manager"""

import sqlite3
from datetime import datetime, date
from typing import Optional, List, Dict
from config import DB_PATH

class Database:
    def __init__(self): self.path = DB_PATH

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INTEGER PRIMARY KEY,
                    username   TEXT,
                    first_name TEXT,
                    joined_at  TEXT DEFAULT (datetime('now')),
                    is_banned  INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS hosted_bots (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id      INTEGER NOT NULL,
                    token         TEXT UNIQUE NOT NULL,
                    username      TEXT NOT NULL,
                    name          TEXT,
                    template_id   TEXT NOT NULL,
                    template_name TEXT NOT NULL,
                    status        TEXT DEFAULT 'stopped',
                    created_at    TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS bot_stats (
                    bot_id       INTEGER PRIMARY KEY,
                    users        INTEGER DEFAULT 0,
                    messages     INTEGER DEFAULT 0,
                    referrals    INTEGER DEFAULT 0,
                    transactions INTEGER DEFAULT 0,
                    last_ping    TEXT
                );
            """)

    # ── Users ──────────────────────────────────────────────────────────────
    def upsert_user(self, uid, uname, fname):
        with self._conn() as c:
            c.execute(
                "INSERT INTO users(id,username,first_name) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name",
                (uid, uname, fname)
            )

    def get_user(self, uid) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(r) if r else None

    def get_all_users(self) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM users WHERE is_banned=0")]

    def ban_user(self, uid):
        with self._conn() as c:
            c.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))

    # ── Bots ───────────────────────────────────────────────────────────────
    def add_bot(self, owner_id, token, username, name, template_id, template_name) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO hosted_bots(owner_id,token,username,name,template_id,template_name) VALUES(?,?,?,?,?,?)",
                (owner_id, token, username, name, template_id, template_name)
            )
            bid = cur.lastrowid
            c.execute("INSERT INTO bot_stats(bot_id) VALUES(?)", (bid,))
            return bid

    def get_bot(self, bid) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM hosted_bots WHERE id=?", (bid,)).fetchone()
            return dict(r) if r else None

    def get_user_bots(self, owner_id) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM hosted_bots WHERE owner_id=? ORDER BY created_at DESC", (owner_id,)
            )]

    def get_all_bots(self) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM hosted_bots ORDER BY created_at DESC")]

    def get_all_running_bots(self) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM hosted_bots WHERE status='running'")]

    def update_bot_status(self, bid, status):
        with self._conn() as c:
            c.execute("UPDATE hosted_bots SET status=? WHERE id=?", (status, bid))

    def delete_bot(self, bid):
        with self._conn() as c:
            c.execute("DELETE FROM bot_stats WHERE bot_id=?", (bid,))
            c.execute("DELETE FROM hosted_bots WHERE id=?", (bid,))

    def bot_token_exists(self, token) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM hosted_bots WHERE token=?", (token,)).fetchone() is not None

    def count_user_bots(self, owner_id) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM hosted_bots WHERE owner_id=?", (owner_id,)).fetchone()[0]

    def count_all_bots(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM hosted_bots").fetchone()[0]

    # ── Stats ──────────────────────────────────────────────────────────────
    def get_bot_stats(self, bid) -> Dict:
        with self._conn() as c:
            r = c.execute("SELECT * FROM bot_stats WHERE bot_id=?", (bid,)).fetchone()
            return dict(r) if r else {}

    def increment_bot_stat(self, bid, field, amt=1):
        if field not in {"users","messages","referrals","transactions"}: return
        with self._conn() as c:
            c.execute(f"UPDATE bot_stats SET {field}={field}+? WHERE bot_id=?", (amt, bid))

    def get_global_stats(self) -> Dict:
        with self._conn() as c:
            total     = c.execute("SELECT COUNT(*) FROM hosted_bots").fetchone()[0]
            running   = c.execute("SELECT COUNT(*) FROM hosted_bots WHERE status='running'").fetchone()[0]
            users     = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            today     = date.today().isoformat()
            today_dep = c.execute("SELECT COUNT(*) FROM hosted_bots WHERE DATE(created_at)=?", (today,)).fetchone()[0]
            top       = c.execute(
                "SELECT template_name, COUNT(*) cnt FROM hosted_bots GROUP BY template_name ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            return {
                "total_bots": total, "running_bots": running,
                "total_users": users, "today_deploys": today_dep,
                "top_templates": [(r["template_name"], r["cnt"]) for r in top],
            }
