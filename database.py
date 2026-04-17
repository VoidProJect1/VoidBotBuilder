"""
⚡ Spike Bot Builder — Database Manager
SQLite-backed persistent storage for all bot data.
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from config import DB_PATH

logger = logging.getLogger("DB")


class Database:
    def __init__(self):
        self.path = DB_PATH

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Schema ─────────────────────────────────────────────────────────────────
    def init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY,
                    username    TEXT,
                    first_name  TEXT,
                    joined_at   TEXT DEFAULT (datetime('now')),
                    is_banned   INTEGER DEFAULT 0
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
                    created_at    TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(owner_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS bot_stats (
                    bot_id     INTEGER PRIMARY KEY,
                    users      INTEGER DEFAULT 0,
                    messages   INTEGER DEFAULT 0,
                    referrals  INTEGER DEFAULT 0,
                    last_ping  TEXT,
                    FOREIGN KEY(bot_id) REFERENCES hosted_bots(id)
                );
            """)
        logger.info("✅ Database initialized.")

    # ── Users ──────────────────────────────────────────────────────────────────
    def upsert_user(self, uid: int, username: str, first_name: str):
        with self._conn() as c:
            c.execute(
                "INSERT INTO users(id, username, first_name) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
                (uid, username, first_name)
            )

    def get_user(self, uid: int) -> Optional[Dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return dict(row) if row else None

    def is_banned(self, uid: int) -> bool:
        u = self.get_user(uid)
        return bool(u and u.get("is_banned"))

    def ban_user(self, uid: int):
        with self._conn() as c:
            c.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))

    def get_all_users(self) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM users WHERE is_banned=0")]

    # ── Bots ───────────────────────────────────────────────────────────────────
    def add_bot(self, owner_id, token, username, name, template_id, template_name) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO hosted_bots(owner_id,token,username,name,template_id,template_name) "
                "VALUES(?,?,?,?,?,?)",
                (owner_id, token, username, name, template_id, template_name)
            )
            bot_id = cur.lastrowid
            c.execute("INSERT INTO bot_stats(bot_id) VALUES(?)", (bot_id,))
            return bot_id

    def get_bot(self, bot_id: int) -> Optional[Dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM hosted_bots WHERE id=?", (bot_id,)).fetchone()
            return dict(row) if row else None

    def get_user_bots(self, owner_id: int) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM hosted_bots WHERE owner_id=? ORDER BY created_at DESC",
                (owner_id,)
            )]

    def get_all_running_bots(self) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM hosted_bots WHERE status='running'"
            )]

    def update_bot_status(self, bot_id: int, status: str):
        with self._conn() as c:
            c.execute("UPDATE hosted_bots SET status=? WHERE id=?", (status, bot_id))

    def delete_bot(self, bot_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM bot_stats WHERE bot_id=?", (bot_id,))
            c.execute("DELETE FROM hosted_bots WHERE id=?", (bot_id,))

    def bot_token_exists(self, token: str) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM hosted_bots WHERE token=?", (token,)
            ).fetchone() is not None

    def count_user_bots(self, owner_id: int) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM hosted_bots WHERE owner_id=?", (owner_id,)
            ).fetchone()[0]

    def count_all_bots(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM hosted_bots").fetchone()[0]

    # ── Stats ──────────────────────────────────────────────────────────────────
    def get_bot_stats(self, bot_id: int) -> Dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM bot_stats WHERE bot_id=?", (bot_id,)).fetchone()
            return dict(row) if row else {}

    def increment_bot_stat(self, bot_id: int, field: str, amount: int = 1):
        valid = {"users", "messages", "referrals"}
        if field not in valid:
            return
        with self._conn() as c:
            c.execute(
                f"UPDATE bot_stats SET {field}={field}+? WHERE bot_id=?",
                (amount, bot_id)
            )

    def get_global_stats(self) -> Dict:
        with self._conn() as c:
            total_bots = c.execute("SELECT COUNT(*) FROM hosted_bots").fetchone()[0]
            running = c.execute("SELECT COUNT(*) FROM hosted_bots WHERE status='running'").fetchone()[0]
            total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            today = date.today().isoformat()
            today_deploys = c.execute(
                "SELECT COUNT(*) FROM hosted_bots WHERE DATE(created_at)=?", (today,)
            ).fetchone()[0]
            top_rows = c.execute(
                "SELECT template_name, COUNT(*) as cnt FROM hosted_bots "
                "GROUP BY template_name ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            top_templates = [(r["template_name"], r["cnt"]) for r in top_rows]
            return {
                "total_bots": total_bots,
                "running_bots": running,
                "total_users": total_users,
                "today_deploys": today_deploys,
                "top_templates": top_templates,
            }
