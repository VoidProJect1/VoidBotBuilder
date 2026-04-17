"""⚡ Void Bot Builder — Base Template"""
import logging
from telegram.ext import Application

class BaseBotTemplate:
    TEMPLATE_ID   = "base"
    TEMPLATE_NAME = "Base"

    def __init__(self, bot_id: int, token: str, db):
        self.bot_id = bot_id
        self.token  = token
        self.db     = db
        self.log    = logging.getLogger(f"Bot#{bot_id}")

    async def build_app(self) -> Application:
        app = Application.builder().token(self.token).build()
        self.register_handlers(app)
        return app

    def register_handlers(self, app): raise NotImplementedError

    def _conn(self): return self.db._conn()
    def track_msg(self):  self.db.increment_bot_stat(self.bot_id, "messages")
    def track_ref(self):  self.db.increment_bot_stat(self.bot_id, "referrals")
    def track_tx(self):   self.db.increment_bot_stat(self.bot_id, "transactions")
    def track_user(self): self.db.increment_bot_stat(self.bot_id, "users")
