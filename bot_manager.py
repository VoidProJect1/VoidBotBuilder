"""
⚡ Spike Bot Builder — Bot Manager
Handles launching, stopping, and tracking hosted bot instances.
Each user bot runs as an independent asyncio task.
"""

import asyncio
import logging
from typing import Dict, Optional
from telegram.ext import Application

logger = logging.getLogger("BotManager")


class BotManager:
    """Manages multiple hosted Telegram bots as background asyncio tasks."""

    def __init__(self, db):
        self.db = db
        self._running: Dict[int, asyncio.Task] = {}  # bot_id → asyncio.Task
        self._apps: Dict[int, Application] = {}       # bot_id → Application

    async def start_bot(self, bot_data: dict) -> bool:
        """Start a hosted bot by bot_data dict from DB."""
        bot_id = bot_data["id"]
        token = bot_data["token"]
        template_id = bot_data["template_id"]

        # Stop if already running
        self.stop_bot(bot_id)

        try:
            from templates import get_template_class
            TemplateClass = get_template_class(template_id)
            if not TemplateClass:
                logger.error(f"Unknown template: {template_id}")
                return False

            template = TemplateClass(bot_id=bot_id, token=token, db=self.db)
            app = await template.build_app()
            self._apps[bot_id] = app

            task = asyncio.create_task(
                self._run_app(bot_id, app),
                name=f"bot_{bot_id}"
            )
            self._running[bot_id] = task
            logger.info(f"✅ Bot #{bot_id} (@{bot_data.get('username', '?')}) started")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to start bot #{bot_id}: {e}")
            return False

    async def _run_app(self, bot_id: int, app: Application):
        """Run the app's updater (polling) until cancelled."""
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(allowed_updates=["message", "callback_query"])
            # Keep running until cancelled
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info(f"Bot #{bot_id} task cancelled.")
        except Exception as e:
            logger.error(f"Bot #{bot_id} crashed: {e}")
            self.db.update_bot_status(bot_id, "stopped")
        finally:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception:
                pass

    def stop_bot(self, bot_id: int):
        """Stop a running hosted bot."""
        task = self._running.pop(bot_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"⏸️ Bot #{bot_id} stopped.")
        self._apps.pop(bot_id, None)

    def is_running(self, bot_id: int) -> bool:
        task = self._running.get(bot_id)
        return task is not None and not task.done()

    async def restart_all_running(self, application=None):
        """On builder startup, restart all bots that were running."""
        bots = self.db.get_all_running_bots()
        logger.info(f"♻️ Restarting {len(bots)} previously running bots...")
        for bot in bots:
            try:
                success = await self.start_bot(bot)
                if not success:
                    self.db.update_bot_status(bot["id"], "stopped")
            except Exception as e:
                logger.error(f"Failed to restart bot #{bot['id']}: {e}")
                self.db.update_bot_status(bot["id"], "stopped")
        logger.info("♻️ Restart complete.")
