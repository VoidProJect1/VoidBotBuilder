"""
templates/url_shortener.py
===========================
URL Shortener Bot
- Uses free public API (tinyurl.com) by default — no key needed
- Admin can set a private API key (e.g. Bitly, CleanUri) for more limits
- Tracks per-user shortened URLs with history
- Custom alias support (API-dependent)
- Admin: set API provider, set API key, view stats, broadcast
- Full keyboard UI with back/cancel
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from templates.base import BaseTemplate

logger = logging.getLogger(__name__)

TEMPLATE_INFO = {
    "id":          "url_shortener",
    "name":        "URL Shortener",
    "emoji":       "🔗",
    "category":    "Utility",
    "description": "Shorten URLs via public API; admin adds private key for higher limits",
    "features":    [
        "Free TinyURL by default (no key needed)",
        "Admin adds Bitly/CleanUri API key for more",
        "Per-user URL history (last 10)",
        "URL validation before shortening",
        "Copy-friendly output",
        "Usage stats per user",
        "Admin broadcast & stats",
    ],
    "complexity":  "Beginner",
    "best_for":    "Utility & productivity bots",
    "stars":       4,
    "new":         False,
}

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# ── API providers ─────────────────────────────────────────────────────────────

async def shorten_tinyurl(url: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://tinyurl.com/api-create.php",
                params={"url": url},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                text = await r.text()
                return text.strip() if text.startswith("http") else None
    except Exception as e:
        logger.error("TinyURL error: %s", e)
        return None

async def shorten_bitly(url: str, api_key: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api-ssl.bitly.com/v4/shorten",
                json={"long_url": url},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                data = await r.json()
                return data.get("link")
    except Exception as e:
        logger.error("Bitly error: %s", e)
        return None

async def shorten_cleanuri(url: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://cleanuri.com/api/v1/shorten",
                data={"url": url},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                data = await r.json()
                return data.get("result_url")
    except Exception as e:
        logger.error("CleanURI error: %s", e)
        return None

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("🔗 Shorten URL", callback_data="url_shorten"),
         InlineKeyboardButton("📜 My History", callback_data="url_history")],
        [InlineKeyboardButton("📊 My Stats", callback_data="url_stats"),
         InlineKeyboardButton("ℹ️ How to Use", callback_data="url_how")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="url_admin")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="url_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="url_main")]])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Set API Provider", callback_data="url_adm_provider"),
         InlineKeyboardButton("🗝 Set API Key", callback_data="url_adm_apikey")],
        [InlineKeyboardButton("📈 Bot Stats", callback_data="url_adm_stats"),
         InlineKeyboardButton("📨 Broadcast", callback_data="url_adm_broadcast")],
        [InlineKeyboardButton("🔍 Current Config", callback_data="url_adm_config"),
         InlineKeyboardButton("🗑 Clear API Key", callback_data="url_adm_clear_key")],
        [InlineKeyboardButton("⬅️ Back", callback_data="url_main")],
    ])

def kb_providers():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 TinyURL (Free, No Key)", callback_data="url_set_prov_tinyurl")],
        [InlineKeyboardButton("🔵 Bitly (API Key Required)", callback_data="url_set_prov_bitly")],
        [InlineKeyboardButton("🟡 CleanURI (Free)", callback_data="url_set_prov_cleanuri")],
        [InlineKeyboardButton("⬅️ Back", callback_data="url_admin")],
    ])

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_get_setting(db, bot_id, key, default=None):
    row = await db.fetchone("SELECT value FROM url_settings WHERE bot_id=? AND key=?", (bot_id, key))
    return row["value"] if row else default

async def db_set_setting(db, bot_id, key, value):
    await db.execute("""
        INSERT INTO url_settings (bot_id, key, value) VALUES (?,?,?)
        ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

async def db_ensure_user(db, uid, username):
    await db.execute("""
        INSERT OR IGNORE INTO url_users (user_id, username, count)
        VALUES (?,?,0)
    """, (uid, username or ""))
    await db.commit()

async def db_log_url(db, uid, original, short):
    await db.execute(
        "INSERT INTO url_history (user_id, original, short, created_at) VALUES (?,?,?,?)",
        (uid, original, short, datetime.utcnow().isoformat())
    )
    await db.execute("UPDATE url_users SET count=count+1 WHERE user_id=?", (uid,))
    await db.commit()

# ── Template ──────────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    async def _do_shorten(self, url: str) -> str | None:
        provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
        api_key = await db_get_setting(self.db, self.bot_id, "api_key", "")

        if provider == "bitly":
            if not api_key:
                # Fall back to tinyurl
                return await shorten_tinyurl(url)
            return await shorten_bitly(url, api_key)
        elif provider == "cleanuri":
            return await shorten_cleanuri(url)
        else:
            return await shorten_tinyurl(url)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
        await update.message.reply_text(
            f"🔗 *URL Shortener Bot*\n\n"
            f"Provider: *{provider.title()}*\n\n"
            f"Send any URL or use the menu below:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        await db_ensure_user(self.db, uid, q.from_user.username)

        if data == "url_main":
            ctx.user_data.clear()
            provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
            await q.edit_message_text(
                f"🔗 *URL Shortener*\nProvider: *{provider.title()}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )

        elif data == "url_shorten":
            ctx.user_data["action"] = "waiting_url"
            provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
            await q.edit_message_text(
                f"🔗 *Shorten a URL*\nProvider: {provider.title()}\n\nSend the URL to shorten:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data == "url_history":
            rows = await self.db.fetchall(
                "SELECT * FROM url_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)
            )
            if not rows:
                await q.edit_message_text("📜 No history yet. Shorten a URL first!",
                                           reply_markup=kb_back())
                return
            lines = ["📜 *Your Recent URLs*\n"]
            for r in rows:
                orig = r["original"][:40] + "..." if len(r["original"]) > 40 else r["original"]
                lines.append(f"• `{r['short']}`\n  _{orig}_")
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

        elif data == "url_stats":
            row = await self.db.fetchone("SELECT * FROM url_users WHERE user_id=?", (uid,))
            count = row["count"] if row else 0
            rank = (await self.db.fetchone(
                "SELECT COUNT(*)+1 AS r FROM url_users WHERE count > ?", (count,)
            ))["r"]
            await q.edit_message_text(
                f"📊 *Your Stats*\n\n🔗 URLs Shortened: {count}\n🏅 Rank: #{rank}",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        elif data == "url_how":
            provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
            api_key = await db_get_setting(self.db, self.bot_id, "api_key", "")
            status = "✅ Private API Key Active" if api_key else "🟢 Free Public API"
            await q.edit_message_text(
                f"ℹ️ *How to Use*\n\n"
                f"1. Tap 'Shorten URL' or just send a URL\n"
                f"2. Get your shortened link instantly\n"
                f"3. View history of past links\n\n"
                f"Provider: *{provider.title()}*\n"
                f"Status: {status}",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        elif data == "url_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_admin())

        elif data == "url_adm_provider":
            if not self.is_admin(uid): return
            await q.edit_message_text("🔑 *Select API Provider:*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_providers())

        elif data.startswith("url_set_prov_"):
            if not self.is_admin(uid): return
            prov = data.replace("url_set_prov_", "")
            await db_set_setting(self.db, self.bot_id, "provider", prov)
            await q.edit_message_text(f"✅ Provider set to *{prov.title()}*",
                                       parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup([[
                                           InlineKeyboardButton("⬅️ Admin", callback_data="url_admin")
                                       ]]))

        elif data == "url_adm_apikey":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "set_api_key"
            await q.edit_message_text(
                "🗝 *Set Private API Key*\n\nFor Bitly: get your key from bitly.com/settings/api\n\nSend your API key now:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="url_admin")]])
            )

        elif data == "url_adm_clear_key":
            if not self.is_admin(uid): return
            await db_set_setting(self.db, self.bot_id, "api_key", "")
            await q.edit_message_text("✅ API key cleared. Using public API.",
                                       reply_markup=InlineKeyboardMarkup([[
                                           InlineKeyboardButton("⬅️ Admin", callback_data="url_admin")
                                       ]]))

        elif data == "url_adm_config":
            if not self.is_admin(uid): return
            provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
            api_key = await db_get_setting(self.db, self.bot_id, "api_key", "")
            key_display = f"{api_key[:8]}..." if api_key else "Not set (using free API)"
            await q.edit_message_text(
                f"🔍 *Current Config*\n\nProvider: {provider}\nAPI Key: `{key_display}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="url_admin")]])
            )

        elif data == "url_adm_stats":
            if not self.is_admin(uid): return
            total_users = (await self.db.fetchone("SELECT COUNT(*) AS c FROM url_users"))["c"]
            total_urls = (await self.db.fetchone("SELECT COUNT(*) AS c FROM url_history"))["c"]
            top = await self.db.fetchall(
                "SELECT username, count FROM url_users ORDER BY count DESC LIMIT 5"
            )
            top_lines = [f"  @{r['username'] or '?'}: {r['count']}" for r in top]
            await q.edit_message_text(
                f"📈 *Bot Stats*\n\nUsers: {total_users}\nTotal URLs: {total_urls}\n\nTop Users:\n" + "\n".join(top_lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="url_admin")]])
            )

        elif data == "url_adm_broadcast":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "broadcast"
            await q.edit_message_text("📨 Send broadcast message:", reply_markup=kb_cancel())

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        await db_ensure_user(self.db, uid, update.effective_user.username)
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="url_main")]])
        back_admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="url_admin")]])

        # Admin actions
        action = ctx.user_data.get("adm_action")
        if action and self.is_admin(uid):
            if action == "set_api_key":
                await db_set_setting(self.db, self.bot_id, "api_key", text)
                ctx.user_data.clear()
                await update.message.reply_text(
                    f"✅ API key saved! (`{text[:8]}...`)",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_admin_kb
                )
            elif action == "broadcast":
                users = await self.db.fetchall("SELECT user_id FROM url_users")
                sent = failed = 0
                for u in users:
                    try:
                        await update.get_bot().send_message(u["user_id"], text)
                        sent += 1
                    except Exception:
                        failed += 1
                ctx.user_data.clear()
                await update.message.reply_text(f"📨 Sent: {sent}, Failed: {failed}", reply_markup=back_admin_kb)
            return

        # URL shortening (inline or via button flow)
        if ctx.user_data.get("action") == "waiting_url" or URL_PATTERN.search(text):
            url_match = URL_PATTERN.search(text)
            if not url_match:
                await update.message.reply_text(
                    "❌ No valid URL found. Send a URL starting with http:// or https://",
                    reply_markup=back_kb
                )
                ctx.user_data.clear()
                return
            url = url_match.group(0)
            ctx.user_data.clear()

            msg = await update.message.reply_text("⏳ Shortening...")
            short = await self._do_shorten(url)
            if not short:
                await msg.edit_text(
                    "❌ Failed to shorten URL. Try again later.",
                    reply_markup=back_kb
                )
                return
            await db_log_url(self.db, uid, url, short)
            provider = await db_get_setting(self.db, self.bot_id, "provider", "tinyurl")
            await msg.edit_text(
                f"✅ *URL Shortened!*\n\n"
                f"Original: `{url[:60]}{'...' if len(url)>60 else ''}`\n\n"
                f"Short: `{short}`\n\n"
                f"Provider: {provider.title()}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Shorten Another", callback_data="url_shorten"),
                     InlineKeyboardButton("🏠 Menu", callback_data="url_main")]
                ])
            )

    async def build_app(self) -> Application:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS url_users (
                user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', count INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS url_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                original TEXT, short TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS url_settings (
                bot_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(bot_id,key))""",
        ]:
            await self.db.execute(ddl)
        await self.db.commit()

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("admin", self._cmd_admin))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
        return app

    async def _cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Not authorized.")
            return
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=kb_admin())
