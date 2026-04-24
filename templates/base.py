"""
⚡ Void Bot Builder — Base Template
────────────────────────────────────
All template classes must inherit from BaseTemplate.
It gives every template free access to:
  - self.bot_id   → hosted_bots.id (integer)
  - self.token    → the bot's Telegram API token
  - self.db       → Database instance
  - self.is_admin → helper to check ADMIN_IDS
"""

from config import ADMIN_IDS
from database import Database


class BaseTemplate:
    def __init__(self, *, bot_id: int, token: str, db: Database):
        self.bot_id = bot_id
        self.token  = token
        self.db     = db

    def is_admin(self, user_id: int) -> bool:
        """Return True if user_id is in the global ADMIN_IDS list."""
        return user_id in ADMIN_IDS

    async def build_app(self):
        """
        REQUIRED override.
        Build and return a configured telegram.ext.Application.
        Do NOT call initialize() or start() — BotManager does that.
        """
        raise NotImplementedError("Template must implement build_app()")
