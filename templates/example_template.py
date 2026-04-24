"""
╔══════════════════════════════════════════════════════════════════╗
║         ⚡ VOID BOT BUILDER — TEMPLATE BLUEPRINT                 ║
║                                                                  ║
║  Copy this file, rename it, fill in the two required sections:  ║
║    1. TEMPLATE_INFO  — metadata shown in the builder menu        ║
║    2. Template class — the actual bot logic                      ║
║                                                                  ║
║  File naming:  templates/my_cool_bot.py                          ║
║  The file is auto-discovered — nothing else needs to change.     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from templates.base import BaseTemplate   # ← always inherit from this

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  SECTION 1 — TEMPLATE METADATA  (required, must be named exactly
#              TEMPLATE_INFO at module level)
# ══════════════════════════════════════════════════════════════════

TEMPLATE_INFO = {
    # ── Identity ─────────────────────────────────────────────────
    "id":          "example_bot",      # UNIQUE snake_case id — used as the DB key
    "name":        "Example Bot",      # Shown in the Templates Store list
    "emoji":       "🤖",               # Emoji prefix in the store list
    "category":    "Utility",          # Free-text category label

    # ── Store listing ─────────────────────────────────────────────
    "description": "A minimal example bot showing the required structure.",
    "features": [                      # Shown as ✅ bullet points in the detail card
        "Feature one — what users get",
        "Feature two — another highlight",
        "Admin broadcast to all users",
        "Inline buttons & callback support",
    ],
    "complexity":  "Beginner",         # Beginner / Intermediate / Advanced
    "best_for":    "Developers learning the template system",

    # ── Store badge ───────────────────────────────────────────────
    "stars": 3,                        # 1-5 — shown as ⭐⭐⭐ when new=False
    "new":   False,                    # True → shows 🔥 NEW badge instead of stars
}


# ══════════════════════════════════════════════════════════════════
#  SECTION 2 — TEMPLATE CLASS  (required, must be named exactly
#              "Template" and inherit BaseTemplate)
# ══════════════════════════════════════════════════════════════════

class Template(BaseTemplate):
    """
    Minimal working template.  Override build_app() to register all
    your handlers, then add whatever commands/callbacks you need.
    """

    # ── build_app ─────────────────────────────────────────────────
    # REQUIRED.  Must return a fully configured but NOT yet started
    # telegram.ext.Application.  BotManager calls initialize/start
    # itself after build_app() returns.
    async def build_app(self) -> Application:
        app = Application.builder().token(self.token).build()

        # Register handlers here ↓
        app.add_handler(CommandHandler("start",  self.cmd_start))
        app.add_handler(CommandHandler("help",   self.cmd_help))
        app.add_handler(CommandHandler("admin",  self.cmd_admin))   # admin only
        app.add_handler(CallbackQueryHandler(self.cb_router))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

        return app

    # ── /start ────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        # self.db  → Database instance (full access to all DB methods)
        # self.bot_id → integer id of this hosted bot in hosted_bots table
        self.db.increment_bot_stat(self.bot_id, "users")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ℹ️ About", callback_data="about")],
            [InlineKeyboardButton("💬 Help",  callback_data="help")],
        ])
        await update.message.reply_text(
            f"👋 Hello {user.first_name}!\nWelcome to the Example Bot.",
            reply_markup=kb,
        )

    # ── /help ─────────────────────────────────────────────────────
    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 *Help*\n\n/start — Main menu\n/help — This message",
            parse_mode="Markdown",
        )

    # ── /admin  (only works for Telegram user IDs listed in ADMIN_IDS) ──
    async def cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Admins only!")
            return
        stats = self.db.get_bot_stats(self.bot_id)
        await update.message.reply_text(
            f"📊 *Bot Stats*\n"
            f"Users: {stats.get('users', 0)}\n"
            f"Messages: {stats.get('messages', 0)}",
            parse_mode="Markdown",
        )

    # ── Inline-button router ──────────────────────────────────────
    async def cb_router(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data  = query.data

        if data == "about":
            await query.edit_message_text("🤖 This is the Example Bot template.")
        elif data == "help":
            await query.edit_message_text("📖 Send /help for the full help text.")
        else:
            await query.edit_message_text("❓ Unknown action.")

    # ── Plain text messages ────────────────────────────────────────
    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self.db.increment_bot_stat(self.bot_id, "messages")
        await update.message.reply_text(f"You said: {update.message.text}")
