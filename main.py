"""
╔═══════════════════════════════════════════════╗
║       ⚡ SPIKE BOT BUILDER BOT ⚡              ║
║   The Ultimate Telegram Bot Factory           ║
╚═══════════════════════════════════════════════╝
"""

import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

from config import BUILDER_TOKEN, ADMIN_IDS, BOT_VERSION
from database import Database
from bot_manager import BotManager
from templates import BOT_TEMPLATES, get_template_info

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("⚡ SpikeBuilder")

# ── Conversation States ────────────────────────────────────────────────────────
MAIN_MENU, AWAIT_TOKEN, SELECT_TEMPLATE, CONFIRM_DEPLOY = range(4)

db = Database()
bot_mgr = BotManager(db)


# ═══════════════════════════════════════════════════════════════════════════════
#                              🎨  UI BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    count = db.count_user_bots(user_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add New Bot", callback_data="add_bot"),
            InlineKeyboardButton(f"🤖 My Bots [{count}]", callback_data="my_bots"),
        ],
        [
            InlineKeyboardButton("🛍️ Bot Templates", callback_data="templates"),
            InlineKeyboardButton("📊 Global Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("📖 How It Works", callback_data="howto"),
            InlineKeyboardButton("👑 Admin Panel", callback_data="admin"),
        ],
        [
            InlineKeyboardButton("💬 Support Chat", url="https://t.me/SpikeSupport"),
        ],
    ])


def template_kb(include_back=True) -> InlineKeyboardMarkup:
    rows = []
    for tid, t in BOT_TEMPLATES.items():
        rows.append([InlineKeyboardButton(
            f"{t['emoji']}  {t['name']}  {'⭐' * t['stars']}",
            callback_data=f"tpl_{tid}"
        )])
    if include_back:
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def back_kb(target="main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Menu", callback_data=target)
    ]])


def mybot_kb(bots: list) -> InlineKeyboardMarkup:
    rows = []
    for b in bots:
        icon = "🟢" if b["status"] == "running" else "🔴"
        rows.append([InlineKeyboardButton(
            f"{icon} @{b['username']} — {b['template_name']}",
            callback_data=f"botmenu_{b['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Another Bot", callback_data="add_bot")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def bot_action_kb(bot_id: int, status: str) -> InlineKeyboardMarkup:
    if status == "running":
        toggle = ("⏸️ Stop Bot", f"stop_{bot_id}")
    else:
        toggle = ("▶️ Start Bot", f"start_{bot_id}")
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(toggle[0], callback_data=toggle[1]),
            InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{bot_id}"),
        ],
        [
            InlineKeyboardButton("📊 Bot Stats", callback_data=f"botstats_{bot_id}"),
            InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"delete_{bot_id}"),
        ],
        [InlineKeyboardButton("🔙 My Bots", callback_data="my_bots")],
    ])


BANNER = (
    "╔════════════════════════════════════╗\n"
    "║  ⚡  SPIKE BOT BUILDER  ⚡          ║\n"
    "║     Your Personal Bot Factory      ║\n"
    "╚════════════════════════════════════╝"
)


def welcome_text(name: str, total: int) -> str:
    return (
        f"`{BANNER}`\n\n"
        f"👋 Hey **{name}**! Welcome to **Spike Bot Builder** 🚀\n\n"
        "The most powerful Telegram bot deployment platform!\n\n"
        "🔥 **Bots You Can Deploy:**\n"
        "╠ 🎁  Refer & Earn Bot\n"
        "╠ 🚀  Advanced Refer & Earn Bot\n"
        "╠ 🎯  Quiz & Trivia Bot\n"
        "╠ 📢  Mass Broadcast Bot\n"
        "╚ 👋  Group Welcome Manager Bot\n\n"
        "⚡ **How It Works:**\n"
        "Paste your **@BotFather token** → pick a template → your bot goes live in seconds! 🎉\n\n"
        f"🌍 _Currently powering **{total}** active bots worldwide!_"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#                          🚀  HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "User")
    total = db.count_all_bots()
    msg = welcome_text(user.first_name or "Friend", total)
    kb = main_menu_kb(user.id)
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    ctx.user_data.clear()
    return MAIN_MENU


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚡ **SPIKE BOT BUILDER — Commands**\n\n"
        "/start — 🏠 Open main menu\n"
        "/addbot — ➕ Add & deploy a new bot\n"
        "/mybots — 🤖 View & manage your bots\n"
        "/help — ❓ Show this message\n\n"
        "📖 Tap /start → How It Works for full guide"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_bot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    msg = (
        "➕ **ADD YOUR BOT**\n\n"
        "📋 **Step 1 — Enter Bot Token**\n\n"
        "To get your token:\n"
        "1️⃣ Open [@BotFather](https://t.me/BotFather)\n"
        "2️⃣ Send /newbot → follow the steps\n"
        "3️⃣ Copy the token it gives you\n\n"
        "🔐 Token format:\n"
        "`1234567890:ABCdefGhiJKLmnoPQRstUvWxYZ`\n\n"
        "⬇️ **Paste your token below:**"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]])
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return AWAIT_TOKEN


async def mybots_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_my_bots(update, ctx)


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "main_menu":
        return await start(update, ctx)
    elif data == "add_bot":
        return await add_bot_cmd(update, ctx)
    elif data == "my_bots":
        return await show_my_bots(update, ctx)
    elif data == "stats":
        return await show_global_stats(update, ctx)
    elif data == "templates":
        await query.edit_message_text(
            "🛍️ **BOT TEMPLATES**\n\nPick a template to view details and deploy:\n\n"
            "⭐⭐⭐ = Premium  |  ⭐⭐ = Popular  |  ⭐ = Standard",
            reply_markup=template_kb(), parse_mode="Markdown"
        )
        return MAIN_MENU
    elif data == "howto":
        return await show_howto(update, ctx)
    elif data == "admin":
        return await show_admin(update, ctx)

    elif data.startswith("tpl_"):
        tid = data[4:]
        info = get_template_info(tid)
        if not info:
            await query.answer("❌ Template not found!", show_alert=True)
            return MAIN_MENU
        feats = "\n".join([f"  ✅ {f}" for f in info["features"]])
        msg = (
            f"{info['emoji']} **{info['name']}**\n"
            f"{'⭐' * info['stars']} | 📂 {info['category']}\n\n"
            f"💬 _{info['description']}_\n\n"
            f"🔥 **Features:**\n{feats}\n\n"
            f"⚙️ Complexity: **{info['complexity']}**\n"
            f"👥 Best For: _{info['best_for']}_"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Deploy This Bot", callback_data=f"deploy_{tid}")],
            [InlineKeyboardButton("🔙 All Templates", callback_data="templates")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        return MAIN_MENU

    elif data.startswith("deploy_"):
        tid = data[7:]
        ctx.user_data["selected_template"] = tid
        return await add_bot_cmd(update, ctx)

    elif data.startswith("botmenu_"):
        return await show_bot_menu(update, ctx, int(data[8:]))

    elif data.startswith("stop_"):
        bid = int(data[5:])
        bot_mgr.stop_bot(bid)
        db.update_bot_status(bid, "stopped")
        await query.answer("⏸️ Bot stopped!", show_alert=True)
        return await show_bot_menu(update, ctx, bid)

    elif data.startswith("start_"):
        bid = int(data[6:])
        bot_info = db.get_bot(bid)
        if bot_info:
            await bot_mgr.start_bot(bot_info)
            db.update_bot_status(bid, "running")
        await query.answer("▶️ Bot started!", show_alert=True)
        return await show_bot_menu(update, ctx, bid)

    elif data.startswith("restart_"):
        bid = int(data[8:])
        bot_mgr.stop_bot(bid)
        bot_info = db.get_bot(bid)
        if bot_info:
            await bot_mgr.start_bot(bot_info)
            db.update_bot_status(bid, "running")
        await query.answer("🔄 Bot restarted!", show_alert=True)
        return await show_bot_menu(update, ctx, bid)

    elif data.startswith("delete_"):
        bid = int(data[7:])
        bot_mgr.stop_bot(bid)
        db.delete_bot(bid)
        await query.answer("🗑️ Bot deleted!", show_alert=True)
        return await show_my_bots(update, ctx)

    elif data.startswith("botstats_"):
        return await show_bot_stats(update, ctx, int(data[9:]))

    elif data == "confirm_deploy":
        return await deploy_bot(update, ctx)

    elif data == "cancel_deploy":
        ctx.user_data.clear()
        return await start(update, ctx)

    return MAIN_MENU


async def token_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()
    if ":" not in token or len(token) < 30:
        await update.message.reply_text(
            "❌ **Invalid token format!**\n\n"
            "Expected format:\n`1234567890:ABCdefGhiJKLmnoPQRst`\n\nTry again 👇",
            parse_mode="Markdown"
        )
        return AWAIT_TOKEN

    msg = await update.message.reply_text("⏳ Validating token with Telegram...")

    try:
        test_app = Application.builder().token(token).build()
        bot_info = await test_app.bot.get_me()
        await test_app.shutdown()
    except Exception:
        await msg.edit_text(
            "❌ **Invalid Token!**\n\nCould not connect. Please check and try again.",
            parse_mode="Markdown"
        )
        return AWAIT_TOKEN

    if db.bot_token_exists(token):
        await msg.edit_text(
            f"⚠️ **Already Registered!**\n\n"
            f"Bot @{bot_info.username} is already hosted here.\n"
            "Use /mybots to manage it.",
            parse_mode="Markdown"
        )
        return MAIN_MENU

    ctx.user_data["token"] = token
    ctx.user_data["bot_username"] = bot_info.username
    ctx.user_data["bot_name"] = bot_info.first_name

    await msg.edit_text(
        f"✅ **Token Verified!**\n\n"
        f"🤖 Bot: **@{bot_info.username}**\n"
        f"📛 Name: {bot_info.first_name}\n\n"
        "Now choose a template 👇",
        parse_mode="Markdown"
    )

    tid = ctx.user_data.pop("selected_template", None)
    if tid:
        # If template was pre-selected from deploy button
        info = get_template_info(tid)
        ctx.user_data["selected_template"] = tid
        msg2 = (
            f"✅ **Confirm Deployment**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Bot: @{bot_info.username}\n"
            f"{info['emoji']} Template: {info['name']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚀 Ready to deploy?"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Deploy!", callback_data="confirm_deploy"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_deploy"),
            ]
        ])
        await update.message.reply_text(msg2, reply_markup=kb, parse_mode="Markdown")
        return CONFIRM_DEPLOY

    await update.message.reply_text(
        "📋 **Step 2 — Choose Template:**",
        reply_markup=template_kb(include_back=False),
        parse_mode="Markdown"
    )
    return SELECT_TEMPLATE


async def template_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        ctx.user_data.clear()
        return await start(update, ctx)

    if not data.startswith("tpl_"):
        return SELECT_TEMPLATE

    tid = data[4:]
    info = get_template_info(tid)
    if not info:
        await query.answer("Template not found!", show_alert=True)
        return SELECT_TEMPLATE

    ctx.user_data["selected_template"] = tid
    uname = ctx.user_data.get("bot_username", "?")
    token = ctx.user_data.get("token", "")
    token_short = token[:12] + "..." if len(token) > 12 else token

    msg = (
        f"✅ **Confirm Deployment**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Bot:** @{uname}\n"
        f"{info['emoji']} **Template:** {info['name']}\n"
        f"🔑 **Token:** `{token_short}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 Your bot will be live in seconds!"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Deploy Now!", callback_data="confirm_deploy"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_deploy"),
        ]
    ])
    await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return CONFIRM_DEPLOY


async def deploy_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    uid = query.from_user.id
    token = ctx.user_data.get("token")
    tid = ctx.user_data.get("selected_template")
    uname = ctx.user_data.get("bot_username", "unknown")
    name = ctx.user_data.get("bot_name", "Bot")

    if not token or not tid:
        await query.edit_message_text("❌ Session expired. Please /start again.")
        return MAIN_MENU

    info = get_template_info(tid)
    await query.edit_message_text(
        f"⏳ **Deploying @{uname}...**\n\n"
        f"🔧 Configuring {info['emoji']} {info['name']}\n"
        f"⚡ Connecting to Telegram API...",
        parse_mode="Markdown"
    )

    bot_id = db.add_bot(
        owner_id=uid, token=token, username=uname,
        name=name, template_id=tid, template_name=info["name"]
    )
    bot_data = db.get_bot(bot_id)
    success = await bot_mgr.start_bot(bot_data)

    if success:
        db.update_bot_status(bot_id, "running")
        status_msg = (
            f"🎉 **Bot Deployed Successfully!**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Status: **Live & Running** 🟢\n"
            f"🤖 Bot: @{uname}\n"
            f"{info['emoji']} Template: {info['name']}\n"
            f"🆔 ID: #{bot_id}\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔗 [Test your bot](https://t.me/{uname}) — it's live! 🎊"
        )
    else:
        status_msg = (
            f"⚠️ **Bot Registered**\n\n"
            f"@{uname} has been registered with {info['name']}.\n"
            f"It will be active shortly. Use /mybots to manage."
        )

    ctx.user_data.clear()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 My Bots", callback_data="my_bots"),
         InlineKeyboardButton("➕ Add Another", callback_data="add_bot")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])
    await query.edit_message_text(status_msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def show_my_bots(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    bots = db.get_user_bots(uid)
    if not bots:
        msg = (
            "🤖 **My Bots**\n\n"
            "You haven't deployed any bots yet!\n\n"
            "Tap ➕ Add New Bot to get started 🚀"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add New Bot", callback_data="add_bot")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ])
    else:
        running = sum(1 for b in bots if b["status"] == "running")
        msg = (
            f"🤖 **My Bots** — {len(bots)} total\n\n"
            f"🟢 Running: {running}  |  🔴 Stopped: {len(bots) - running}\n\n"
            "Select a bot to manage:"
        )
        kb = mybot_kb(bots)
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def show_bot_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bot_id: int) -> int:
    b = db.get_bot(bot_id)
    if not b:
        await update.callback_query.answer("Bot not found!", show_alert=True)
        return MAIN_MENU
    icon = "🟢 Running" if b["status"] == "running" else "🔴 Stopped"
    info = get_template_info(b["template_id"]) or {}
    msg = (
        f"{info.get('emoji', '🤖')} **@{b['username']}**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 Name: {b['name']}\n"
        f"📋 Template: {b['template_name']}\n"
        f"📊 Status: {icon}\n"
        f"🆔 Bot ID: #{bot_id}\n"
        f"📅 Added: {b.get('created_at', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.callback_query.edit_message_text(
        msg, reply_markup=bot_action_kb(bot_id, b["status"]), parse_mode="Markdown"
    )
    return MAIN_MENU


async def show_bot_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bot_id: int) -> int:
    b = db.get_bot(bot_id)
    if not b:
        return MAIN_MENU
    stats = db.get_bot_stats(bot_id)
    msg = (
        f"📊 **Stats — @{b['username']}**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: {stats.get('users', 0)}\n"
        f"💬 Messages: {stats.get('messages', 0)}\n"
        f"🔗 Referrals: {stats.get('referrals', 0)}\n"
        f"⏱️ Uptime: {stats.get('uptime', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back", callback_data=f"botmenu_{bot_id}")
    ]])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def show_global_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    s = db.get_global_stats()
    lines = [
        "📊 **SPIKE BOT BUILDER — Stats**\n",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🌍 Total Bots: **{s['total_bots']}**",
        f"🟢 Running: **{s['running_bots']}**",
        f"👥 Total Users: **{s['total_users']}**",
        f"🚀 Deployed Today: **{s['today_deploys']}**",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "\n🏆 **Top Templates:**",
    ]
    for i, (name, count) in enumerate(s.get("top_templates", []), 1):
        lines.append(f"  {i}. {name} — {count} bots")
    lines.append(f"\n⚡ Version: **{BOT_VERSION}**")
    await update.callback_query.edit_message_text(
        "\n".join(lines), reply_markup=back_kb(), parse_mode="Markdown"
    )
    return MAIN_MENU


async def show_howto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = (
        "📖 **HOW SPIKE BOT BUILDER WORKS**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**1️⃣ Create Your Bot**\n"
        "• Open [@BotFather](https://t.me/BotFather)\n"
        "• Send /newbot → pick name & username\n"
        "• Copy the API token\n\n"
        "**2️⃣ Paste Token Here**\n"
        "• Tap ➕ Add New Bot\n"
        "• Paste your token — validated instantly ✅\n\n"
        "**3️⃣ Choose Template**\n"
        "• 🎁 Refer & Earn Bot\n"
        "• 🚀 Advanced Refer & Earn\n"
        "• 🎯 Quiz Bot\n"
        "• 📢 Broadcast Bot\n"
        "• 👋 Welcome Bot\n\n"
        "**4️⃣ Live in Seconds! 🎉**\n"
        "Your bot is fully deployed.\n"
        "Manage it anytime from My Bots 🤖\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "❓ [@SpikeSupport](https://t.me/SpikeSupport)"
    )
    await update.callback_query.edit_message_text(
        msg, reply_markup=back_kb(), parse_mode="Markdown"
    )
    return MAIN_MENU


async def show_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.callback_query.answer("⛔ Admin only!", show_alert=True)
        return MAIN_MENU
    s = db.get_global_stats()
    msg = (
        "👑 **ADMIN PANEL**\n\n"
        f"🌍 Bots: {s['total_bots']}  🟢 Running: {s['running_bots']}\n"
        f"👥 Users: {s['total_users']}  🚀 Today: {s['today_deploys']}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("📋 All Bots", callback_data="admin_allbots"),
        ],
        [
            InlineKeyboardButton("♻️ Restart All", callback_data="admin_restart_all"),
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


# ═══════════════════════════════════════════════════════════════════════════════
#                              🏁  MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("⚡ Spike Bot Builder starting up...")
    db.init()

    app = Application.builder().token(BUILDER_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("mybots", mybots_cmd),
            CommandHandler("addbot", add_bot_cmd),
        ],
        states={
            MAIN_MENU: [CallbackQueryHandler(button_handler)],
            AWAIT_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, token_received),
                CallbackQueryHandler(button_handler),
            ],
            SELECT_TEMPLATE: [
                CallbackQueryHandler(template_selected),
            ],
            CONFIRM_DEPLOY: [
                CallbackQueryHandler(button_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))

    async def post_init(application):
        await application.bot.set_my_commands([
            ("start", "🏠 Open main menu"),
            ("addbot", "➕ Add a new bot"),
            ("mybots", "🤖 Manage your bots"),
            ("help", "❓ Help & guide"),
        ])
        await bot_mgr.restart_all_running(application)
        logger.info("✅ Spike Bot Builder is LIVE!")

    app.post_init = post_init

    logger.info("🚀 Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
