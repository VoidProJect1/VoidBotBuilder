"""⚡ Void Bot Builder — Bot Manager"""
import asyncio, logging
from telegram.ext import Application

logger = logging.getLogger("BotManager")

class BotManager:
    def __init__(self, db):
        self.db   = db
        self._run = {}   # bid → Task
        self._app = {}   # bid → Application

    async def start_bot(self, bot_data: dict) -> bool:
        bid = bot_data["id"]
        self.stop_bot(bid)
        try:
            from templates import get_template_class
            Cls = get_template_class(bot_data["template_id"])
            if not Cls: return False
            tpl = Cls(bot_id=bid, token=bot_data["token"], db=self.db)
            app = await tpl.build_app()
            self._app[bid] = app
            self._run[bid] = asyncio.create_task(self._run_app(bid, app), name=f"bot_{bid}")
            logger.info(f"✅ Bot #{bid} @{bot_data.get('username')} started")
            return True
        except Exception as e:
            logger.error(f"❌ Bot #{bid} start failed: {e}")
            return False

    async def _run_app(self, bid, app):
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(allowed_updates=["message","callback_query","poll_answer","chat_member"])
            while True: await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info(f"Bot #{bid} cancelled")
        except Exception as e:
            logger.error(f"Bot #{bid} crashed: {e}")
            self.db.update_bot_status(bid, "stopped")
        finally:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except: pass

    def stop_bot(self, bid):
        t = self._run.pop(bid, None)
        if t and not t.done(): t.cancel()
        self._app.pop(bid, None)

    def is_running(self, bid) -> bool:
        t = self._run.get(bid)
        return t is not None and not t.done()

    async def restart_all_running(self, app=None):
        bots = self.db.get_all_running_bots()
        logger.info(f"♻️ Restarting {len(bots)} bots...")
        for b in bots:
            ok = await self.start_bot(b)
            if not ok: self.db.update_bot_status(b["id"], "stopped")
